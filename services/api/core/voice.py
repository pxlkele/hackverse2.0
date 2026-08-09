"""
Voice in, voice out.

    ASR:  faster-whisper, local, no key
    TTS:  edge-tts, free, no key

Both have a cache keyed on content, because the demo must survive with no
internet and because re-synthesising the same sentence on stage is a needless
risk. Set VOICE_MODE=offline to refuse any network call and use cache only —
run the demo that way.

Deliberately not Bhashini: it needs institutional approval we do not have. The
adapter shape below means adding it later is one function, not a rewrite.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import subprocess
import threading
import time
from functools import lru_cache
from pathlib import Path

CACHE_DIR = Path(__file__).resolve().parent.parent / "data" / "voice_cache"
VOICE_MODE = os.getenv("VOICE_MODE", "auto")  # auto | offline
WHISPER_SIZE = os.getenv("SETU_WHISPER_SIZE", "small")

# edge-tts neural voices. Male by default — our demo persona is a man, and a
# mismatched voice is a small thing that quietly undermines a pitch.
VOICES = {
    "hi": "hi-IN-MadhurNeural",
    "mr": "mr-IN-ManoharNeural",
    "kn": "kn-IN-GaganNeural",
    "ta": "ta-IN-ValluvarNeural",
    "te": "te-IN-MohanNeural",
    "bn": "bn-IN-BashkarNeural",
    "gu": "gu-IN-NiranjanNeural",
    "en": "en-IN-PrabhatNeural",
}


class VoiceError(RuntimeError):
    pass


def _key(text: str, lang: str) -> str:
    return hashlib.sha1(f"{lang}:{text}".encode()).hexdigest()[:20]


# Telugu and Kannada are unusable on `small` — not degraded, but unrelated
# tokens in unrelated scripts, and slower than the languages that work. On
# `medium` both come back with the facts intact, because medium writes numerals
# as digits and digits survive any script:
#
#   te  small 66s / garbage     ->  medium 15s / "ना वयसू 35 ... रोजुकु 800 रूपायल"
#   kn  small 224s / garbage    ->  medium 88s / "ವಾಸು 35 ವಾಷ್ ದಿನಕ್ 800 ರೂಪಾಯ"
#
# Only these two pay medium's cost. Hindi is 6s on small and would be several
# times that on medium, and Hindi is the language the demo actually runs in.
ASR_MODEL_FOR = {"te": "medium", "kn": "medium"}


@lru_cache(maxsize=4)
def _whisper(size: str | None = None):
    from faster_whisper import WhisperModel

    # int8 on CPU: roughly 3x faster than float32 with no meaningful accuracy
    # loss at this size, which matters on a laptop mid-demo.
    return WhisperModel(size or WHISPER_SIZE, device="cpu", compute_type="int8")


ASR_BUDGET_S = float(os.getenv("SETU_ASR_BUDGET_S", "45"))

# Languages we have actually put speech through and read the result back, on the
# model ASR_MODEL_FOR picks for each. This is not the list Whisper claims to
# support — it claims far more, and claims Kannada on `small`, where it returns
# Korean.
#
#   hi  6s, facts intact      ta  13s, and it writes amounts as digits
#   mr  10s                   gu  Gujarati rendered phonetically in Devanagari
#   bn  same, in Devanagari   te  15s on medium      kn  88s on medium
#
# Anything outside this set is refused immediately rather than burning a minute
# to fail. Judge a language by whether age and income survive, not by how close
# the transcript looks to the original: gu, bn and te all score terribly on
# character similarity because Whisper answers in the wrong script, and all
# three are completely recoverable by the parsing tables in profile.py.
ASR_LANGUAGES = {"hi", "en", "mr", "ta", "gu", "bn", "te", "kn"}

# Kannada genuinely needs 88 seconds on medium. That is slow, but it is a real
# answer where the alternative was four minutes of nonsense, so it gets its own
# budget instead of being refused by the shared one.
ASR_BUDGET_FOR = {"kn": 150.0, "te": 90.0}

# One decode at a time. A transcription that blew its budget is still running
# and still holding CPU — we cannot kill the thread, but we must not let it
# compete with the next caller. Measured: a timed-out Kannada decode made a
# following Hindi decode miss a 20s budget it normally meets in 6s.
_ASR_LOCK = threading.Lock()


def transcribe(audio_path: str | Path, language: str = "hi") -> str:
    """
    Speech -> text. Fully local; works with no internet.

    Two guards, both put here after a measured 457-second transcription of a
    14-second Kannada clip:

    `condition_on_previous_text=False` — feeding each window the previous one's
    text is what lets Whisper fall into a repetition loop on a language it is
    weak in. It emits the same fragment over and over, and because each repeat
    becomes context for the next, it does not stop. That one clip produced
    "ूपना। ूपना। ूपना।" for seven and a half minutes.

    `ASR_BUDGET_S` — a hard wall clock. Failing fast and re-prompting is a
    recoverable demo moment; a frozen page is not.
    """
    if language not in ASR_LANGUAGES:
        raise VoiceError(
            f"ASR is not supported for language={language!r} on Whisper "
            f"{WHISPER_SIZE}. Supported: {sorted(ASR_LANGUAGES)}."
        )

    if not _ASR_LOCK.acquire(timeout=1.0):
        raise VoiceError("ASR is busy with a previous clip. Ask the caller to repeat.")

    size = ASR_MODEL_FOR.get(language, WHISPER_SIZE)
    budget = ASR_BUDGET_FOR.get(language, ASR_BUDGET_S)

    def _decode() -> str:
        segments, _info = _whisper(size).transcribe(
            str(audio_path),
            language=language,
            vad_filter=True,      # drops silence and cart noise between phrases
            beam_size=5,
            condition_on_previous_text=False,
            compression_ratio_threshold=2.4,   # discard windows that decoded to mush
        )
        return " ".join(segment.text.strip() for segment in segments).strip()

    # The deadline needs its own thread: a single pathological segment can take
    # minutes on its own, so checking the clock between segments never gets a
    # turn. CTranslate2 drops the GIL while decoding, so the join below really
    # does return on time. We cannot kill the thread, only stop waiting for it —
    # so it releases the lock itself, and a caller who arrives while it is still
    # running is told ASR is busy rather than being left to compete for CPU.
    result: dict[str, str] = {}

    def _run() -> None:
        try:
            result["text"] = _decode()
        except Exception:  # noqa: BLE001 - surfaced as a missing result below
            pass
        finally:
            _ASR_LOCK.release()

    worker = threading.Thread(target=_run, daemon=True)
    worker.start()
    worker.join(budget)
    if worker.is_alive():
        raise VoiceError(
            f"ASR exceeded {budget:.0f}s for language={language!r} on {size}. "
            f"Whisper is weak in this language; the caller should be re-prompted."
        )
    if "text" not in result:
        raise VoiceError(f"ASR failed for language={language!r}.")
    return result.get("text", "")


# How sure Whisper must be before we override the language the client asked for.
# Measured on synthesised speech in all eight: mr .99, ta .99, te .98, hi .97,
# kn .95, bn .68 — all comfortably over. Gujarati lands at .44 and English is
# misread as Hindi at .36, so the threshold sits above both: a weak guess loses
# to what the caller actually selected, which is the safer of the two errors.
DETECT_FLOOR = 0.60


def transcribe_auto(
    audio_path: str | Path, default_language: str = "hi"
) -> tuple[str, str, float]:
    """
    Speech -> (text, language, confidence), detecting the language from the audio.

    A vendor should not have to find their language on a screen before speaking —
    the whole premise is that speaking is the interface. So we listen first and
    answer in whatever they used, falling back to their selection when the guess
    is weak.

    Detection runs on `small` even for Telugu and Kannada, which need `medium` to
    transcribe: identifying a language is a far easier problem than transcribing
    it, and `small` gets te and kn right at .98 and .95. When the detection lands
    on one of those two we re-run on medium for the transcript itself, so the
    extra cost falls only on the languages that need it.
    """
    detected, confidence = default_language, 0.0
    try:
        segments, info = _whisper(WHISPER_SIZE).transcribe(
            str(audio_path), language=None, vad_filter=True, beam_size=5,
            condition_on_previous_text=False, compression_ratio_threshold=2.4,
        )
        text = " ".join(s.text.strip() for s in segments).strip()
        confidence = float(getattr(info, "language_probability", 0.0) or 0.0)
        guess = getattr(info, "language", None)
        if guess in ASR_LANGUAGES and confidence >= DETECT_FLOOR:
            detected = guess
        elif guess == default_language:
            # The guess is weak but it agrees with what the caller already
            # picked, so there is nothing to correct and the decode in hand was
            # made in the right language. Redoing it bought a second identical
            # transcript at full price: Marathi detects at 0.54 against a 0.60
            # floor every single time, which made every Marathi turn pay for
            # two decodes - 11-15s where one costs 4.7-6.7s.
            detected = guess
        else:
            # Weak or unsupported guess: keep the caller's choice, and redo the
            # transcript in it — a Hindi decode of Marathi audio is not what we
            # want to hand the parser.
            text = transcribe(audio_path, language=default_language)
            return text, default_language, confidence
    except VoiceError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise VoiceError(f"language detection failed: {exc}") from exc

    # The two languages `small` cannot transcribe, only recognise.
    if ASR_MODEL_FOR.get(detected) and ASR_MODEL_FOR[detected] != WHISPER_SIZE:
        text = transcribe(audio_path, language=detected)

    return text, detected, confidence


def _run_blocking(coro) -> None:
    """
    Run an async job to completion from either kind of caller.

    asyncio.run() raises if a loop is already running, and `POST /api/ivr/speech`
    is an `async def` — so every answer to a *spoken* question failed TTS here and
    came back with audio_url=None while the typed path worked perfectly. The
    caller only saw "the app shows text but never talks". When we are already on
    a loop, hand the job to a thread that owns a loop of its own.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        asyncio.run(coro)                     # no loop here: the ordinary path
        return

    box: dict[str, BaseException] = {}

    def _worker() -> None:
        try:
            asyncio.run(coro)
        except BaseException as exc:          # noqa: BLE001 - re-raised on the caller's thread
            box["exc"] = exc

    thread = threading.Thread(target=_worker, daemon=True)
    thread.start()
    thread.join()
    if "exc" in box:
        raise box["exc"]


def speak(text: str, lang: str = "hi", force: bool = False) -> Path:
    """
    Text -> mp3. Cached by content, so a rehearsed line is synthesised once and
    then plays from disk forever after.
    """
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    out = CACHE_DIR / f"{_key(text, lang)}.mp3"

    # A zero-byte file means a previous attempt died mid-write (edge-tts creates
    # the file before it streams). Treating it as a hit would serve silence
    # forever, which on stage looks exactly like the demo freezing.
    if out.exists() and out.stat().st_size > 0 and not force:
        return out

    if VOICE_MODE == "offline":
        raise VoiceError(
            f"VOICE_MODE=offline and no cached audio for this text. "
            f"Pre-cache it before going on stage: {text[:60]}..."
        )

    voice = VOICES.get(lang, VOICES["hi"])

    async def _run() -> None:
        import edge_tts

        await edge_tts.Communicate(text, voice).save(str(out))

    try:
        _run_blocking(_run())
    except Exception as exc:  # noqa: BLE001 - any failure must fall back
        out.unlink(missing_ok=True)  # never leave a partial file to be cached
        raise VoiceError(f"TTS failed ({exc}). Pre-cache this line.") from exc

    if out.stat().st_size == 0:
        out.unlink(missing_ok=True)
        raise VoiceError("TTS returned no audio (check the voice id and edge-tts version).")

    return out


def play(path: str | Path) -> None:
    """Play audio through the speakers. macOS afplay; harmless if unavailable."""
    try:
        subprocess.run(["afplay", str(path)], check=False, timeout=60)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass


def precache(lines: list[tuple[str, str]]) -> dict[str, str]:
    """
    Synthesise every demo line ahead of time.

    Call this the moment TTS works. It is the single strongest insurance policy
    in the build — once cached, the demo speaks with the wifi off.
    """
    results: dict[str, str] = {}
    for text, lang in lines:
        try:
            results[text[:48]] = str(speak(text, lang))
        except VoiceError as exc:
            results[text[:48]] = f"FAILED: {exc}"
    return results


def warm() -> None:
    """
    Load the Whisper weights before the first caller speaks.

    Measured on this laptop: the model costs ~10s to load off disk, and
    _whisper() is lru_cached, so without this the very first tap on stage pays
    all of it before ASR even starts. Nothing to do with the network — the
    weights are local; it is purely the first-use penalty.
    """
    try:
        _whisper()
    except Exception:  # noqa: BLE001 - a warm-up must never stop the server
        pass


def is_cached(text: str, lang: str = "hi") -> bool:
    return (CACHE_DIR / f"{_key(text, lang)}.mp3").exists()


def cache_stats() -> dict:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    files = list(CACHE_DIR.glob("*.mp3"))
    return {
        "mode": VOICE_MODE,
        "cached_lines": len(files),
        "cache_dir": str(CACHE_DIR),
        "whisper_size": WHISPER_SIZE,
    }
