"""
TTS must work from an async request handler.

`POST /api/ivr/speech` is an `async def`, so it runs on the event loop. speak()
used asyncio.run() directly, which raises there — every answer to a *spoken*
question lost its audio and came back with audio_url=None, while the typed
path (a sync handler) synthesised fine. On the phone that looked like the app
showing text and never talking, and the replay button then played the previous
turn's "I could not hear you" prompt.

No network here: the synthesis itself is monkeypatched. What is under test is
only that speak() completes on a thread that already owns a running loop.
"""

from __future__ import annotations

import asyncio

import pytest

from services.api.core import voice


@pytest.fixture()
def fake_tts(tmp_path, monkeypatch):
    """Point the cache at tmp and make 'synthesis' write a byte, not call Microsoft."""
    monkeypatch.setattr(voice, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(voice, "VOICE_MODE", "auto")

    class _Communicate:
        def __init__(self, text, v):
            self.text, self.voice = text, v

        async def save(self, path):
            await asyncio.sleep(0)          # a real await, so a dead loop would show
            with open(path, "wb") as fh:
                fh.write(b"\xff\xf3fake-mp3")

    import edge_tts

    monkeypatch.setattr(edge_tts, "Communicate", _Communicate)
    return tmp_path


def test_speak_works_with_no_loop_running(fake_tts):
    path = voice.speak("नमस्ते", "hi")
    assert path.exists() and path.stat().st_size > 0


def test_speak_works_inside_a_running_event_loop(fake_tts):
    """The regression: this raised 'asyncio.run() cannot be called from a
    running event loop', which speak() converted into VoiceError."""

    async def handler():
        # asyncio.to_thread would hide the bug: the handler called speak directly.
        return voice.speak("धन्यवाद", "hi")

    path = asyncio.run(handler())
    assert path.exists() and path.stat().st_size > 0


def test_failure_inside_a_loop_still_raises_voiceerror(fake_tts, monkeypatch):
    """A genuine TTS failure must still degrade to text, not escape as RuntimeError."""
    import edge_tts

    class _Broken:
        def __init__(self, *a):
            pass

        async def save(self, path):
            raise OSError("no network")

    monkeypatch.setattr(edge_tts, "Communicate", _Broken)

    async def handler():
        return voice.speak("कुछ और", "hi")

    with pytest.raises(voice.VoiceError):
        asyncio.run(handler())


def test_no_zero_byte_file_survives_a_failure(fake_tts, monkeypatch):
    """A partial write cached as a hit would serve silence for ever."""
    import edge_tts

    class _Partial:
        def __init__(self, *a):
            pass

        async def save(self, path):
            open(path, "wb").close()        # creates the file, writes nothing
            raise OSError("died mid-stream")

    monkeypatch.setattr(edge_tts, "Communicate", _Partial)

    async def handler():
        return voice.speak("अधूरा", "hi")

    with pytest.raises(voice.VoiceError):
        asyncio.run(handler())
    assert list(fake_tts.glob("*.mp3")) == []
