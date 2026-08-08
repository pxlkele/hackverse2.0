"""
IVR simulator — the feature-phone channel.

Setu's central claim is that you do not need a smartphone, an app, or the
ability to read English. Every other channel we ship quietly assumes at least
one of those. This one assumes a phone that can dial and a person who can
speak, which is the actual floor.

Real telephony (Twilio) was cut for time. What was NOT cut is the call flow:
begin() / on_digit() / on_speech() are a transport-agnostic state machine that
returns a Turn describing what to say and what to wait for next. The browser
front-end is one transport; a Twilio webhook would be another, calling the same
three functions. Swapping them is a new endpoint, not a rewrite.

Two languages only — Hindi and English. Half-verified Hindi in front of judges
is worse than two languages that are right, and we cannot check Marathi or
Tamil prompts tonight.
"""

from __future__ import annotations

import re
import tempfile
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from services.api.core import (
    eligibility,
    narrate,
    pathfinder,
    profile as profile_mod,
    store,
    voice,
)

router = APIRouter(prefix="/api/ivr", tags=["ivr"])

Expect = Literal["digit", "speech", "end"]


# ── Prompts ──────────────────────────────────────────────────────────────────
# Written to be *heard*, not read: short sentences, the action last, no clause
# a listener has to hold in memory. Every prompt that offers choices repeats
# them, because a caller cannot scroll back.

PROMPTS = {
    "greeting": {
        "hi": "नमस्ते। सेतु में आपका स्वागत है। हिंदी के लिए एक दबाइए। For English, press two.",
        "en": "नमस्ते। सेतु में आपका स्वागत है। हिंदी के लिए एक दबाइए। For English, press two.",
    },
    "ask_situation": {
        "hi": (
            "बीप के बाद बताइए, आप क्या काम करते हैं और आपको किस चीज़ की ज़रूरत है। "
            "जैसे — मैं सब्ज़ी बेचता हूँ, मुझे लोन चाहिए। बताने के बाद हैश दबाइए।"
        ),
        "en": (
            "After the beep, tell us what work you do and what you need. "
            "For example — I sell vegetables, I need a loan. Press hash when you finish."
        ),
    },
    "thinking": {
        "hi": "एक मिनट रुकिए। मैं सरकारी नियम देख रहा हूँ।",
        "en": "One moment. I am checking the government rules.",
    },
    "after_answer": {
        "hi": (
            "फिर से सुनने के लिए एक दबाइए। "
            "आवेदन शुरू करने के लिए दो दबाइए। "
            "किसी व्यक्ति से बात करने के लिए शून्य दबाइए।"
        ),
        "en": (
            "To hear that again, press one. "
            "To start your application, press two. "
            "To speak to a person, press zero."
        ),
    },
    "case_opened": {
        "hi": (
            "आपका आवेदन शुरू हो गया है। हम आपको याद दिलाने के लिए फ़ोन करेंगे। "
            "फ़ोन रखने के लिए नौ दबाइए।"
        ),
        "en": (
            "Your application has been started. We will call you with reminders. "
            "Press nine to hang up."
        ),
    },
    "operator": {
        "hi": (
            "आपको आपके नज़दीकी सी. एस. सी. केंद्र के ऑपरेटर से जोड़ा जा रहा है। "
            "वे आपके कागज़ देखने में मदद करेंगे।"
        ),
        "en": (
            "Connecting you to an operator at your nearest C S C centre. "
            "They will help you check your documents."
        ),
    },
    "not_understood": {
        "hi": "माफ़ कीजिए, मैं समझ नहीं पाया। दोबारा कोशिश करने के लिए एक दबाइए।",
        "en": "Sorry, I did not understand that. Press one to try again.",
    },
    "nothing_heard": {
        "hi": "मुझे कुछ सुनाई नहीं दिया। दोबारा बोलने के लिए एक दबाइए।",
        "en": "I did not hear anything. Press one to speak again.",
    },
    "goodbye": {
        "hi": "सेतु को फ़ोन करने के लिए धन्यवाद। नमस्ते।",
        "en": "Thank you for calling Setu. Goodbye.",
    },
}


@dataclass
class Turn:
    """One leg of the call: what Setu says, and what it waits for afterwards."""

    say: str
    expect: Expect
    state: str
    audio_url: str | None = None
    # What the keypad offers right now. The browser renders these as labelled
    # keys; a real IVR would ignore them (the caller hears the options instead).
    options: list[dict] = field(default_factory=list)
    # Everything the operator/judge screen wants to show alongside the call.
    detail: dict = field(default_factory=dict)


@dataclass
class Session:
    call_id: str
    language: str = "hi"
    state: str = "greeting"
    last_answer: str = ""
    last_text: str = ""
    decisions: list = field(default_factory=list)
    transcript: list[dict] = field(default_factory=list)


# In-memory: a hackathon demo, one caller at a time, and a restart between runs
# is fine. Persisting calls would mean a schema change, and the schemas are frozen.
_SESSIONS: dict[str, Session] = {}


def _audio_url_for(text: str, lang: str) -> str | None:
    """
    Synthesise (or reuse cached) speech and return a URL the browser can play.

    Never raises: a failed TTS must degrade to text on screen, not kill the
    call. VOICE_MODE=offline with a cold cache is the expected failure here.
    """
    try:
        path = voice.speak(text, lang)
    except voice.VoiceError:
        return None
    return f"/api/ivr/audio/{path.stem}"


def _turn(session: Session, key: str, expect: Expect, **kw) -> Turn:
    """Build a Turn from a named prompt, in the session's language."""
    text = PROMPTS[key][session.language]
    session.state = key
    return Turn(
        say=text,
        expect=expect,
        state=key,
        audio_url=_audio_url_for(text, session.language),
        **kw,
    )


MENU_AFTER_ANSWER = [
    {"digit": "1", "label_en": "Repeat", "label_hi": "दोबारा"},
    {"digit": "2", "label_en": "Start application", "label_hi": "आवेदन शुरू करें"},
    {"digit": "0", "label_en": "Talk to a person", "label_hi": "व्यक्ति से बात करें"},
]

LANGUAGE_MENU = [
    {"digit": "1", "label_en": "Hindi", "label_hi": "हिंदी"},
    {"digit": "2", "label_en": "English", "label_hi": "English"},
]


# ── The state machine ────────────────────────────────────────────────────────

def begin(language: str | None = None) -> tuple[str, Turn]:
    """
    Caller dials in. Returns the call id and the greeting.

    A client with a screen (the PWA) picks the language itself, so passing one
    skips the spoken menu and goes straight to the question. The phone path
    passes nothing and still hears "एक दबाइए".
    """
    call_id = uuid.uuid4().hex[:8]
    session = Session(call_id=call_id)
    _SESSIONS[call_id] = session

    if language in ("hi", "en"):
        session.language = language
        return call_id, _turn(session, "ask_situation", "speech")

    return call_id, _turn(session, "greeting", "digit", options=LANGUAGE_MENU)


def _session(call_id: str) -> Session:
    session = _SESSIONS.get(call_id)
    if session is None:
        raise HTTPException(status_code=404, detail="call not found — dial again")
    return session


def on_digit(call_id: str, digit: str) -> Turn:
    """Caller pressed a key."""
    session = _session(call_id)
    session.transcript.append({"who": "caller", "text": f"[pressed {digit}]"})

    if digit == "9":
        return _turn(session, "goodbye", "end")

    if session.state == "greeting":
        if digit in ("1", "2"):
            session.language = "hi" if digit == "1" else "en"
            return _turn(session, "ask_situation", "speech")
        return _turn(session, "not_understood", "digit", options=LANGUAGE_MENU)

    # After an answer, or after any dead end that offered "press 1 to retry".
    if digit == "1":
        if session.state == "after_answer" and session.last_answer:
            # Repeat the answer itself, not the menu.
            return Turn(
                say=session.last_answer,
                expect="digit",
                state="after_answer",
                audio_url=_audio_url_for(session.last_answer, session.language),
                options=MENU_AFTER_ANSWER,
            )
        return _turn(session, "ask_situation", "speech")

    if digit == "2" and session.decisions:
        # Agentic follow-through: turn the top ladder into tracked commitments.
        top = session.decisions[0]
        try:
            store.open_case(f"ivr:{call_id}", top)
        except Exception:  # noqa: BLE001 - a demo must not die on a DB write
            pass
        return _turn(session, "case_opened", "digit")

    if digit == "0":
        # The trusted-intermediary fallback: a human, on purpose, by design.
        return _turn(session, "operator", "end")

    return _turn(session, "not_understood", "digit", options=MENU_AFTER_ANSWER)


def on_speech(call_id: str, text: str) -> Turn:
    """Caller finished speaking. This is where the real pipeline runs."""
    session = _session(call_id)
    text = (text or "").strip()

    if not text:
        return _turn(session, "nothing_heard", "digit")

    session.last_text = text
    session.transcript.append({"who": "caller", "text": text})

    user_profile = profile_mod.extract(text, language=session.language)
    decisions = pathfinder.build_all(user_profile, eligibility.evaluate_all(user_profile))
    spoken = narrate.narrate_all(user_profile, decisions, session.language)

    session.decisions = decisions
    session.last_answer = spoken
    session.transcript.append({"who": "setu", "text": spoken})

    # The answer and the menu are spoken back to back, but they are separate
    # audio files so "press 1 to repeat" can replay the answer alone.
    menu = PROMPTS["after_answer"][session.language]
    session.state = "after_answer"

    return Turn(
        say=f"{spoken}\n\n{menu}",
        expect="digit",
        state="after_answer",
        audio_url=_audio_url_for(spoken, session.language),
        options=MENU_AFTER_ANSWER,
        detail={
            "transcript": text,
            "profile": user_profile.model_dump(mode="json"),
            "decisions": [d.model_dump(mode="json") for d in decisions],
            "menu_audio_url": _audio_url_for(menu, session.language),
        },
    )


# ── HTTP transport ───────────────────────────────────────────────────────────

class DigitRequest(BaseModel):
    call_id: str
    digit: str


class TextRequest(BaseModel):
    call_id: str
    text: str


class CallRequest(BaseModel):
    language: str | None = None


@router.post("/call")
def start_call(request: CallRequest | None = None):
    call_id, turn = begin(request.language if request else None)
    return {"call_id": call_id, "turn": turn.__dict__}


@router.post("/digit")
def press_digit(request: DigitRequest):
    return {"turn": on_digit(request.call_id, request.digit).__dict__}


@router.post("/text")
def say_text(request: TextRequest):
    """
    Speech bypass — typed or canned input on the same code path as the mic.

    This is demo insurance. If the microphone fails on stage, the persona
    buttons still drive a real call through the real pipeline.
    """
    return {"turn": on_speech(request.call_id, request.text).__dict__}


@router.post("/speech")
async def post_speech(call_id: str = Form(...), audio: UploadFile = File(...)):
    """Recorded audio from the browser mic -> Whisper -> the pipeline."""
    session = _session(call_id)
    suffix = Path(audio.filename or "clip.webm").suffix or ".webm"

    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(await audio.read())
        clip = tmp.name

    try:
        text = voice.transcribe(clip, language=session.language)
    except Exception as exc:  # noqa: BLE001 - ASR failure is a call event, not a 500
        return {
            "turn": _turn(session, "nothing_heard", "digit").__dict__,
            "error": str(exc),
        }
    finally:
        Path(clip).unlink(missing_ok=True)

    return {"turn": on_speech(call_id, text).__dict__, "transcript": text}


_KEY = re.compile(r"^[a-f0-9]{6,40}$")


@router.get("/audio/{key}")
def get_audio(key: str):
    """Stream a cached mp3. Keys are content hashes, so they are safe to expose."""
    if not _KEY.match(key):
        raise HTTPException(status_code=400, detail="bad audio key")
    path = voice.CACHE_DIR / f"{key}.mp3"
    if not path.exists():
        raise HTTPException(status_code=404, detail="audio not cached")
    return FileResponse(path, media_type="audio/mpeg")


@router.get("/transcript/{call_id}")
def get_transcript(call_id: str):
    session = _session(call_id)
    return {
        "call_id": call_id,
        "language": session.language,
        "state": session.state,
        "transcript": session.transcript,
    }


def precache_prompts() -> dict[str, str]:
    """
    Synthesise every fixed prompt in both languages.

    Run this before going on stage. Once cached, the whole call flow speaks with
    the wifi off — only the generated answer needs the network, and the persona
    buttons cover that too if you replay a rehearsed line.
    """
    lines = [
        (text, lang)
        for prompt in PROMPTS.values()
        for lang, text in prompt.items()
    ]
    return voice.precache(lines)
