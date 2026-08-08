"""
Setu - voice layer (demo-day stack).

The pitch's production stack is Bhashini (IndicConformer ASR + IndicTTS),
but government registration/approval isn't through yet. For the live demo
this uses:
  - faster-whisper for ASR - local, no API key, solid multilingual support
  - edge-tts for TTS - free Microsoft neural voices, no key, genuinely good
    Indic voices

Swap this module out for Bhashini once access comes through. transcribe()
and synthesize() are the only two functions anything upstream calls, so
nothing else needs to change when that swap happens.
"""
import asyncio
import io
import tempfile

from faster_whisper import WhisperModel
import edge_tts

_whisper_model = None

# "small" balances accuracy vs. speed/RAM for a laptop demo. Bump to "medium"
# if you have the compute headroom and want cleaner transcripts.
WHISPER_MODEL_SIZE = "small"

# edge-tts voice IDs. Full list: `edge-tts --list-voices` in your venv.
TTS_VOICES = {
    "hi-IN": "hi-IN-SwaraNeural",
    "mr-IN": "mr-IN-AarohiNeural",
    "ta-IN": "ta-IN-PallaviNeural",
    "te-IN": "te-IN-ShrutiNeural",
    "bn-IN": "bn-IN-TanishaaNeural",
    "kn-IN": "kn-IN-SapnaNeural",
    "gu-IN": "gu-IN-DhwaniNeural",
    "en-IN": "en-IN-NeerjaNeural",
}


def _get_whisper():
    global _whisper_model
    if _whisper_model is None:
        _whisper_model = WhisperModel(WHISPER_MODEL_SIZE, device="cpu", compute_type="int8")
    return _whisper_model


def transcribe(audio_bytes: bytes) -> str:
    """audio_bytes: raw bytes of any audio file faster-whisper/PyAV can
    decode (wav, webm, mp3, ...) - e.g. straight from st.audio_input()."""
    model = _get_whisper()
    with tempfile.NamedTemporaryFile(suffix=".wav") as f:
        f.write(audio_bytes)
        f.flush()
        segments, _info = model.transcribe(f.name, beam_size=5)
        text = " ".join(seg.text.strip() for seg in segments)
    return text.strip()


async def _synthesize_async(text: str, voice: str) -> bytes:
    communicate = edge_tts.Communicate(text, voice)
    buf = io.BytesIO()
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            buf.write(chunk["data"])
    return buf.getvalue()


def synthesize(text: str, language: str = "hi-IN") -> bytes:
    """Returns mp3 bytes. `language` is a key into TTS_VOICES."""
    voice = TTS_VOICES.get(language, TTS_VOICES["hi-IN"])
    return asyncio.run(_synthesize_async(text, voice))


def spoken_portion(answer_text: str) -> str:
    """rag.answer() returns a 4-part formatted response (explanation,
    citation, checklist, confidence). Reading all of that aloud is
    tedious and undercuts the "speaks naturally" pitch - this pulls just
    the plain-language explanation (part 1) for TTS, while the dashboard
    still displays the full formatted text on screen."""
    marker = "\n2."
    idx = answer_text.find(marker)
    if idx == -1:
        return answer_text
    spoken = answer_text[:idx]
    # strip a leading "1." if the model included it
    return spoken.split(". ", 1)[-1].strip() if spoken.strip().startswith("1.") else spoken.strip()


if __name__ == "__main__":
    # quick manual check: synthesize a line and write it to disk
    import sys
    text = " ".join(sys.argv[1:]) or "Namaste, main Setu hoon."
    audio = synthesize(text, "hi-IN")
    with open("voice_test_output.mp3", "wb") as f:
        f.write(audio)
    print(f"Wrote {len(audio)} bytes to voice_test_output.mp3")
