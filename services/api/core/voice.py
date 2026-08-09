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


@lru_cache(maxsize=1)
def _whisper():
    from faster_whisper import WhisperModel

    # int8 on CPU: roughly 3x faster than float32 with no meaningful accuracy
    # loss at this size, which matters on a laptop mid-demo.
    return WhisperModel(WHISPER_SIZE, device="cpu", compute_type="int8")


def transcribe(audio_path: str | Path, language: str = "hi") -> str:
    """Speech -> text. Fully local; works with no internet."""
    segments, _info = _whisper().transcribe(
        str(audio_path),
        language=language,
        vad_filter=True,          # drops silence and cart noise between phrases
        beam_size=5,
    )
    return " ".join(segment.text.strip() for segment in segments).strip()


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
        asyncio.run(_run())
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
