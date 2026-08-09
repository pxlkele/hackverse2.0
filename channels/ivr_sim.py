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

Eight languages, listed in SUPPORTED_LANGUAGES — the one place that list lives.
It started as two, on the reasoning that half-verified Hindi beats two languages
that are right. That still holds, so nothing was added on faith: every language
here has been put through the whole pipeline, ASR to spoken answer, and the
transcripts are in services/api/tests/test_profile.py.

The *spoken* greeting is still a Hindi/English menu, and deliberately so. It
plays before the caller has chosen anything, and reading eight options aloud to
someone holding a feature phone would be worse than useless. Clients with a
screen pass their language to begin() and never hear the menu.
"""

from __future__ import annotations

import os
import re
import tempfile
import time
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
        "mr": (
            "बीप नंतर सांगा, तुम्ही काय काम करता आणि तुम्हाला काय हवं आहे. "
            "जसं — मी भाजी विकतो, मला कर्ज हवं आहे. सांगून झाल्यावर हॅश दाबा."
        ),
        "gu": (
            "બીપ પછી કહો, તમે શું કામ કરો છો અને તમને શું જોઈએ છે. "
            "જેમ કે — હું શાકભાજી વેચું છું, મને લોન જોઈએ છે. કહી લીધા પછી હેશ દબાવો."
        ),
        "bn": (
            "বীপের পরে বলুন, আপনি কী কাজ করেন এবং আপনার কী দরকার। "
            "যেমন — আমি সবজি বিক্রি করি, আমার ঋণ দরকার। বলা শেষ হলে হ্যাশ চাপুন।"
        ),
        "ta": (
            "பீப் சத்தத்திற்குப் பிறகு சொல்லுங்கள், நீங்கள் என்ன வேலை செய்கிறீர்கள், "
            "உங்களுக்கு என்ன தேவை. உதாரணமாக — நான் காய்கறி விற்கிறேன், எனக்கு கடன் வேண்டும். "
            "சொல்லி முடித்ததும் ஹாஷ் அழுத்துங்கள்."
        ),
        "te": (
            "బీప్ తర్వాత చెప్పండి, మీరు ఏ పని చేస్తారు, మీకు ఏమి కావాలి. "
            "ఉదాహరణకు — నేను కూరగాయలు అమ్ముతాను, నాకు రుణం కావాలి. "
            "చెప్పిన తర్వాత హాష్ నొక్కండి."
        ),
        "kn": (
            "ಬೀಪ್ ನಂತರ ಹೇಳಿ, ನೀವು ಏನು ಕೆಲಸ ಮಾಡುತ್ತೀರಿ ಮತ್ತು ನಿಮಗೆ ಏನು ಬೇಕು. "
            "ಉದಾಹರಣೆಗೆ — ನಾನು ತರಕಾರಿ ಮಾರುತ್ತೇನೆ, ನನಗೆ ಸಾಲ ಬೇಕು. "
            "ಹೇಳಿದ ನಂತರ ಹ್ಯಾಶ್ ಒತ್ತಿ."
        ),
    },
    "thinking": {
        "hi": "एक मिनट रुकिए। मैं सरकारी नियम देख रहा हूँ।",
        "en": "One moment. I am checking the government rules.",
        "mr": "एक मिनिट थांबा. मी सरकारी नियम पाहत आहे.",
        "gu": "એક મિનિટ રોકાઓ. હું સરકારી નિયમો જોઈ રહ્યો છું.",
        "bn": "এক মিনিট অপেক্ষা করুন। আমি সরকারি নিয়ম দেখছি।",
        "ta": "ஒரு நிமிடம் காத்திருங்கள். நான் அரசு விதிகளைப் பார்க்கிறேன்.",
        "te": "ఒక నిమిషం ఆగండి. నేను ప్రభుత్వ నియమాలు చూస్తున్నాను.",
        "kn": "ಒಂದು ನಿಮಿಷ ಕಾಯಿರಿ. ನಾನು ಸರ್ಕಾರಿ ನಿಯಮಗಳನ್ನು ನೋಡುತ್ತಿದ್ದೇನೆ.",
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
        "mr": (
            "पुन्हा ऐकण्यासाठी एक दाबा. अर्ज सुरू करण्यासाठी दोन दाबा. "
            "एखाद्या व्यक्तीशी बोलण्यासाठी शून्य दाबा."
        ),
        "gu": (
            "ફરી સાંભળવા માટે એક દબાવો. અરજી શરૂ કરવા માટે બે દબાવો. "
            "કોઈ વ્યક્તિ સાથે વાત કરવા માટે શૂન્ય દબાવો."
        ),
        "bn": (
            "আবার শুনতে এক চাপুন। আবেদন শুরু করতে দুই চাপুন। "
            "কারও সঙ্গে কথা বলতে শূন্য চাপুন।"
        ),
        "ta": (
            "மீண்டும் கேட்க ஒன்று அழுத்துங்கள். விண்ணப்பத்தைத் தொடங்க இரண்டு அழுத்துங்கள். "
            "ஒருவருடன் பேச பூஜ்ஜியம் அழுத்துங்கள்."
        ),
        "te": (
            "మళ్ళీ వినడానికి ఒకటి నొక్కండి. దరఖాస్తు ప్రారంభించడానికి రెండు నొక్కండి. "
            "ఒక వ్యక్తితో మాట్లాడటానికి సున్నా నొక్కండి."
        ),
        "kn": (
            "ಮತ್ತೆ ಕೇಳಲು ಒಂದು ಒತ್ತಿ. ಅರ್ಜಿ ಪ್ರಾರಂಭಿಸಲು ಎರಡು ಒತ್ತಿ. "
            "ಒಬ್ಬ ವ್ಯಕ್ತಿಯೊಂದಿಗೆ ಮಾತನಾಡಲು ಸೊನ್ನೆ ಒತ್ತಿ."
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
        "mr": (
            "तुमचा अर्ज सुरू झाला आहे. आम्ही तुम्हाला आठवण करून देण्यासाठी फोन करू. "
            "फोन ठेवण्यासाठी नऊ दाबा."
        ),
        "gu": (
            "તમારી અરજી શરૂ થઈ ગઈ છે. અમે તમને યાદ કરાવવા ફોન કરીશું. "
            "ફોન મૂકવા માટે નવ દબાવો."
        ),
        "bn": (
            "আপনার আবেদন শুরু হয়েছে। আমরা আপনাকে মনে করিয়ে দিতে ফোন করব। "
            "ফোন রাখতে নয় চাপুন।"
        ),
        "ta": (
            "உங்கள் விண்ணப்பம் தொடங்கிவிட்டது. நினைவூட்ட நாங்கள் அழைப்போம். "
            "அழைப்பை முடிக்க ஒன்பது அழுத்துங்கள்."
        ),
        "te": (
            "మీ దరఖాస్తు ప్రారంభమైంది. గుర్తు చేయడానికి మేము ఫోన్ చేస్తాము. "
            "ఫోన్ పెట్టేయడానికి తొమ్మిది నొక్కండి."
        ),
        "kn": (
            "ನಿಮ್ಮ ಅರ್ಜಿ ಪ್ರಾರಂಭವಾಗಿದೆ. ನೆನಪಿಸಲು ನಾವು ಫೋನ್ ಮಾಡುತ್ತೇವೆ. "
            "ಫೋನ್ ಇಡಲು ಒಂಬತ್ತು ಒತ್ತಿ."
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
        "mr": (
            "तुम्हाला तुमच्या जवळच्या सी. एस. सी. केंद्रातील ऑपरेटरशी जोडत आहोत. "
            "ते तुमचे कागद पाहण्यात मदत करतील."
        ),
        "gu": (
            "તમને તમારા નજીકના સી. એસ. સી. કેન્દ્રના ઓપરેટર સાથે જોડી રહ્યા છીએ. "
            "તેઓ તમારા કાગળ જોવામાં મદદ કરશે."
        ),
        "bn": (
            "আপনাকে আপনার নিকটতম সি. এস. সি. কেন্দ্রের অপারেটরের সঙ্গে যোগ করা হচ্ছে। "
            "তাঁরা আপনার কাগজ দেখতে সাহায্য করবেন।"
        ),
        "ta": (
            "உங்கள் அருகிலுள்ள சி. எஸ். சி. மையத்தின் ஆபரேட்டருடன் இணைக்கிறோம். "
            "அவர்கள் உங்கள் ஆவணங்களைப் பார்க்க உதவுவார்கள்."
        ),
        "te": (
            "మీ దగ్గరి సి. ఎస్. సి. కేంద్రం ఆపరేటర్‌తో కలుపుతున్నాము. "
            "వారు మీ పత్రాలు చూడటానికి సహాయం చేస్తారు."
        ),
        "kn": (
            "ನಿಮ್ಮ ಹತ್ತಿರದ ಸಿ. ಎಸ್. ಸಿ. ಕೇಂದ್ರದ ಆಪರೇಟರ್‌ಗೆ ಜೋಡಿಸುತ್ತಿದ್ದೇವೆ. "
            "ಅವರು ನಿಮ್ಮ ದಾಖಲೆಗಳನ್ನು ನೋಡಲು ಸಹಾಯ ಮಾಡುತ್ತಾರೆ."
        ),
    },
    "not_understood": {
        "hi": "माफ़ कीजिए, मैं समझ नहीं पाया। दोबारा कोशिश करने के लिए एक दबाइए।",
        "en": "Sorry, I did not understand that. Press one to try again.",
        "mr": "माफ करा, मला समजलं नाही. पुन्हा प्रयत्न करण्यासाठी एक दाबा.",
        "gu": "માફ કરો, મને સમજાયું નહીં. ફરી પ્રયત્ન કરવા માટે એક દબાવો.",
        "bn": "দুঃখিত, আমি বুঝতে পারিনি। আবার চেষ্টা করতে এক চাপুন।",
        "ta": "மன்னிக்கவும், எனக்குப் புரியவில்லை. மீண்டும் முயற்சிக்க ஒன்று அழுத்துங்கள்.",
        "te": "క్షమించండి, నాకు అర్థం కాలేదు. మళ్ళీ ప్రయత్నించడానికి ఒకటి నొక్కండి.",
        "kn": "ಕ್ಷಮಿಸಿ, ನನಗೆ ಅರ್ಥವಾಗಲಿಲ್ಲ. ಮತ್ತೆ ಪ್ರಯತ್ನಿಸಲು ಒಂದು ಒತ್ತಿ.",
    },
    "nothing_heard": {
        "hi": "मुझे कुछ सुनाई नहीं दिया। दोबारा बोलने के लिए एक दबाइए।",
        "en": "I did not hear anything. Press one to speak again.",
        "mr": "मला काही ऐकू आलं नाही. पुन्हा बोलण्यासाठी एक दाबा.",
        "gu": "મને કંઈ સંભળાયું નહીં. ફરી બોલવા માટે એક દબાવો.",
        "bn": "আমি কিছু শুনতে পাইনি। আবার বলতে এক চাপুন।",
        "ta": "எனக்கு எதுவும் கேட்கவில்லை. மீண்டும் பேச ஒன்று அழுத்துங்கள்.",
        "te": "నాకు ఏమీ వినిపించలేదు. మళ్ళీ మాట్లాడటానికి ఒకటి నొక్కండి.",
        "kn": "ನನಗೆ ಏನೂ ಕೇಳಿಸಲಿಲ್ಲ. ಮತ್ತೆ ಮಾತನಾಡಲು ಒಂದು ಒತ್ತಿ.",
    },
    "goodbye": {
        "hi": "सेतु को फ़ोन करने के लिए धन्यवाद। नमस्ते।",
        "en": "Thank you for calling Setu. Goodbye.",
        "mr": "सेतुला फोन केल्याबद्दल धन्यवाद. नमस्कार.",
        "gu": "સેતુને ફોન કરવા બદલ આભાર. નમસ્તે.",
        "bn": "সেতুতে ফোন করার জন্য ধন্যবাদ। নমস্কার।",
        "ta": "சேதுவை அழைத்ததற்கு நன்றி. வணக்கம்.",
        "te": "సేతుకు ఫోన్ చేసినందుకు ధన్యవాదాలు. నమస్కారం.",
        "kn": "ಸೇತುಗೆ ಫೋನ್ ಮಾಡಿದ್ದಕ್ಕೆ ಧನ್ಯವಾದಗಳು. ನಮಸ್ಕಾರ.",
    },
}

# The offered languages, and the only place that list lives. voice.ASR_LANGUAGES
# says what we can *hear*; this says what we can hold a whole conversation in,
# which additionally needs a prompt set and a TTS voice.
#
# The greeting deliberately stays a Hindi/English menu: it is spoken before the
# caller has chosen anything, and reading eight options aloud to someone on a
# feature phone would be worse than useless. A client with a screen passes its
# language to begin() and never hears the menu at all.
SUPPORTED_LANGUAGES = ("hi", "en", "mr", "gu", "bn", "ta", "te", "kn")

LANGUAGE_LABELS = {
    "hi": "हिंदी", "en": "English", "mr": "मराठी", "gu": "ગુજરાતી",
    "bn": "বাংলা", "ta": "தமிழ்", "te": "తెలుగు", "kn": "ಕನ್ನಡ",
}


def prompt_text(key: str, lang: str) -> str:
    """
    A fixed prompt, falling back rather than raising.

    PROMPTS[key][lang] would KeyError the moment a language is offered before its
    prompts are written, and a KeyError here is a dead call.
    """
    options = PROMPTS[key]
    return options.get(lang) or options.get("hi") or next(iter(options.values()))


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
    text = prompt_text(key, session.language)
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

    if language in SUPPORTED_LANGUAGES:
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
    menu = prompt_text("after_answer", session.language)
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
            # Carries *_local fields beside the originals: the card reads in the
            # caller's language while the audited values stay untouched.
            "decisions": narrate.localise_decisions(decisions, session.language),
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


@router.get("/languages")
def languages():
    """
    What the client should offer, and whether each one can speak offline.

    The PWA builds its language picker from this rather than hardcoding a list,
    so adding a language is one entry in SUPPORTED_LANGUAGES and not an edit in
    two files that drift apart.
    """
    silent = {lang for _key, lang in missing_prompt_audio()}
    return {
        "languages": [
            {
                "code": code,
                "label": LANGUAGE_LABELS.get(code, code),
                "speaks_offline": code not in silent,
            }
            for code in SUPPORTED_LANGUAGES
        ]
    }


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


DEBUG_CLIPS = Path(__file__).resolve().parent.parent / "services" / "api" / "data" / "debug_clips"


@router.post("/speech")
async def post_speech(call_id: str = Form(...), audio: UploadFile = File(...)):
    """
    Recorded audio from the browser mic -> Whisper -> the pipeline.

    Everything here is logged, because it was not and that cost real debugging
    time: a failure returned "I did not hear anything" with a 200 and the reason
    only in the response body, so the server log showed a clean success for an
    ASR timeout, a busy lock, a zero-byte upload and genuine silence alike. Four
    different problems, one indistinguishable symptom.

    Set SETU_DEBUG_CLIPS=1 to keep the uploaded audio. A clip from the actual
    phone is the only way to tell "the mic recorded nothing" from "we could not
    decode what the mic sent".
    """
    session = _session(call_id)
    suffix = Path(audio.filename or "clip.webm").suffix or ".webm"
    raw = await audio.read()

    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(raw)
        clip = tmp.name

    if os.getenv("SETU_DEBUG_CLIPS") == "1":
        DEBUG_CLIPS.mkdir(parents=True, exist_ok=True)
        kept = DEBUG_CLIPS / f"{call_id}-{int(time.time())}{suffix}"
        kept.write_bytes(raw)
        print(f"ivr/speech: kept {kept}", flush=True)

    started = time.monotonic()
    try:
        # Answer in the language they spoke, not the one they tapped. Someone who
        # speaks Marathi into a screen still set to Hindi should get Marathi back;
        # expecting them to find their language first defeats the whole premise.
        text, detected, confidence = voice.transcribe_auto(
            clip, default_language=session.language
        )
        if detected != session.language:
            print(
                f"ivr/speech language switched {session.language} -> {detected} "
                f"(p={confidence:.2f}) call={call_id}",
                flush=True,
            )
            session.language = detected
    except Exception as exc:  # noqa: BLE001 - ASR failure is a call event, not a 500
        print(
            f"ivr/speech FAILED call={call_id} lang={session.language} "
            f"bytes={len(raw)} name={audio.filename!r} type={audio.content_type!r} "
            f"after={time.monotonic() - started:.1f}s: {type(exc).__name__}: {exc}",
            flush=True,
        )
        return {
            "turn": _turn(session, "nothing_heard", "digit").__dict__,
            "error": str(exc),
            "reason": type(exc).__name__,
        }
    finally:
        Path(clip).unlink(missing_ok=True)

    print(
        f"ivr/speech call={call_id} lang={session.language} bytes={len(raw)} "
        f"name={audio.filename!r} type={audio.content_type!r} "
        f"asr={time.monotonic() - started:.1f}s chars={len(text)} text={text[:80]!r}",
        flush=True,
    )
    if not text.strip():
        # Genuine silence and an undecodable container look identical to the
        # caller; say so in the log at least.
        print(
            f"ivr/speech EMPTY TRANSCRIPT call={call_id} — {len(raw)} bytes of "
            f"{audio.content_type!r} decoded to nothing",
            flush=True,
        )
    return {
        "turn": on_speech(call_id, text).__dict__,
        "transcript": text,
        # So the client can move its own UI to the language that was actually
        # spoken, rather than staying on the chip the caller tapped.
        "language": session.language,
    }


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
    Synthesise every fixed prompt in every offered language.

    Run this before going on stage. edge-tts synthesises over the network, so an
    uncached line cannot be spoken with the wifi off — it degrades to text, which
    for a voice-first product is the demo failing quietly. Once this has run, the
    entire call flow speaks offline in all eight languages; only a novel
    generated answer still needs the wire.
    """
    lines = [
        (text, lang)
        for prompt in PROMPTS.values()
        for lang, text in prompt.items()
    ]
    return voice.precache(lines)


def missing_prompt_audio() -> list[tuple[str, str]]:
    """Which (key, language) pairs would be silent offline right now."""
    return [
        (key, lang)
        for key, prompt in PROMPTS.items()
        for lang, text in prompt.items()
        if not voice.is_cached(text, lang)
    ]
