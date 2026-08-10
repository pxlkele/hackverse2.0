"""
Twilio webhook — real phone calls + missed-call callback.

Two entry points:

  INBOUND  — caller dials the number, stays on, talks to Setu.
             POST /twilio/incoming  →  greeting TwiML

  MISSED-CALL CALLBACK — caller dials and hangs up before answer.
             Twilio fires POST /twilio/incoming with CallStatus=no-answer
             OR the call completes in <2s (ring and drop).
             We detect this and immediately call THEM back via the REST API.
             Free for the user: they pay nothing, we pay ~₹0.01/min.

Trial-account note: Twilio trial can only dial VERIFIED numbers outbound.
For the demo, verify +919731002427 at console.twilio.com/phone-numbers/verified.
Any other number gets error 21216 — tell judges that's a $1 upgrade away.

ngrok setup (one-time):
    ngrok http 8000
    bash setup_twilio.sh   ← sets webhook + PUBLIC_URL automatically
"""

from __future__ import annotations

import logging
import os
import threading
import time

import httpx
from fastapi import APIRouter, Form, Response

from channels.ivr_sim import begin, on_chat, on_digit, on_speech, Turn, _SESSIONS
from services.api.core import phone_bus


# Twilio speech-recognition language codes (BCP-47). Trial accounts can't use
# <Record>, so we ask Twilio to transcribe with <Gather input="speech">
# instead. Fall back to Hindi-English bilingual if we don't know yet.
_TWILIO_SPEECH_LANG = {
    "hi": "hi-IN", "en": "en-IN", "mr": "mr-IN", "gu": "gu-IN",
    "bn": "bn-IN", "ta": "ta-IN", "te": "te-IN", "kn": "kn-IN",
}


def _speech_lang_for(call_id: str | None) -> str:
    if not call_id:
        return "hi-IN"
    session = _SESSIONS.get(call_id)
    if session and session.language:
        return _TWILIO_SPEECH_LANG.get(session.language, "hi-IN")
    return "hi-IN"

router = APIRouter(prefix="/twilio", tags=["twilio"])
log = logging.getLogger("setu.twilio")

# Public URL of this server (the ngrok https URL).
# Set by setup_twilio.sh → written to .env → loaded here.
PUBLIC_URL = os.getenv("PUBLIC_URL", "").rstrip("/")

ACCOUNT_SID   = os.getenv("TWILIO_ACCOUNT_SID", "")
AUTH_TOKEN    = os.getenv("TWILIO_AUTH_TOKEN", "")
FROM_NUMBER   = os.getenv("TWILIO_PHONE_NUMBER", "")

# How long the inbound call must ring before we treat it as a missed call.
# A genuine caller stays on; someone doing a missed-call drop hangs up in <5s.
MISSED_CALL_MAX_DURATION = 15  # seconds — international ring can be slow


def _twiml(turn: Turn, call_id: str | None = None) -> str:
    """
    Render a Turn as TwiML.

    Twilio trial accounts cannot use <Record>, so all speech capture goes
    through <Gather input="speech"> — Twilio's own STT. The transcript
    comes back as the `SpeechResult` form field on the action URL.

    All Gathers point at /twilio/gather, which branches by payload:
      - Digits present → on_digit
      - SpeechResult present → on_chat (if chatting) or on_speech (else)
    """
    speech_lang = _speech_lang_for(call_id)
    lines = ['<?xml version="1.0" encoding="UTF-8"?>', "<Response>"]

    def _play_lines(indent: str) -> list[str]:
        out: list[str] = []
        if turn.audio_url and PUBLIC_URL:
            out.append(f'{indent}<Play>{PUBLIC_URL}{turn.audio_url}</Play>')
            menu_url = (turn.detail or {}).get("menu_audio_url") if hasattr(turn, "detail") else None
            if menu_url:
                out.append(f'{indent}<Play>{PUBLIC_URL}{menu_url}</Play>')
        else:
            safe = turn.say.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            out.append(f'{indent}<Say voice="Polly.Aditi" language="hi-IN">{safe}</Say>')
        return out

    # ── chat mode: accept both digits (0/1) and speech in one Gather ────────
    if turn.state == "chatting":
        lines.append(
            f'  <Gather input="dtmf speech" numDigits="1" timeout="5" '
            f'speechTimeout="auto" language="{speech_lang}" '
            f'action="{PUBLIC_URL}/twilio/gather" method="POST">'
        )
        lines.extend(_play_lines("    "))
        lines.append("  </Gather>")
        lines.append("</Response>")
        return "\n".join(lines)

    # ── digit menus (greeting language pick, after_answer, not_understood) ──
    if turn.expect == "digit":
        lines.append(
            f'  <Gather input="dtmf" numDigits="1" timeout="12" '
            f'action="{PUBLIC_URL}/twilio/gather" method="POST">'
        )
        lines.extend(_play_lines("    "))
        lines.append("  </Gather>")
    # ── ask_situation, need_more, chat_paused, chat_restart: speech capture ─
    elif turn.expect == "speech":
        lines.append(
            f'  <Gather input="speech" timeout="5" speechTimeout="auto" '
            f'language="{speech_lang}" '
            f'action="{PUBLIC_URL}/twilio/gather" method="POST">'
        )
        lines.extend(_play_lines("    "))
        lines.append("  </Gather>")
    elif turn.expect == "end":
        lines.extend(_play_lines("  "))
        lines.append("  <Hangup/>")

    lines.append("</Response>")
    return "\n".join(lines)


def _xml(body: str) -> Response:
    return Response(content=body, media_type="application/xml")


# ── Per-call state ────────────────────────────────────────────────────────────
_CALL_MAP:   dict[str, str]   = {}   # CallSid → our call_id
_CALL_START: dict[str, float] = {}   # CallSid → epoch time of /incoming


# ── Missed-call callback ──────────────────────────────────────────────────────

def _call_back(to: str) -> None:
    """
    Dial the caller back using the Twilio REST API.

    Runs in a background thread so the status webhook returns immediately.
    The call connects and Twilio hits /twilio/incoming — same greeting as
    if they had stayed on the line.
    """
    if not all([ACCOUNT_SID, AUTH_TOKEN, FROM_NUMBER, PUBLIC_URL]):
        log.warning("Missed-call callback skipped — Twilio env not fully configured.")
        return

    try:
        with httpx.Client(timeout=15) as client:
            # Trial accounts reject StatusCallback* parameters (error: "Invalid
            # or disallowed parameters provided - trial accounts have limited
            # parameter access"). Send only the essentials — call still connects
            # and hits /twilio/incoming; we just don't get an end-of-call ping.
            resp = client.post(
                f"https://api.twilio.com/2010-04-01/Accounts/{ACCOUNT_SID}/Calls.json",
                auth=(ACCOUNT_SID, AUTH_TOKEN),
                data={
                    "To":   to,
                    "From": FROM_NUMBER,
                    "Url":  f"{PUBLIC_URL}/twilio/incoming",
                },
            )
        if resp.status_code == 201:
            log.info("Callback initiated to %s", to)
        else:
            log.warning("Callback failed %s: %s", resp.status_code, resp.text[:200])
    except Exception as exc:  # noqa: BLE001
        log.warning("Callback error: %s", exc)


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/incoming")
async def incoming(
    CallSid: str = Form(...),
    From:    str = Form(default=""),
    CallStatus: str = Form(default=""),
):
    """
    Twilio calls this when someone dials in OR when we call them back.

    Both paths start a fresh IVR session and return the greeting TwiML.
    """
    call_id, turn = begin()   # language=None → bilingual greeting
    _CALL_MAP[CallSid]   = call_id
    _CALL_START[CallSid] = time.monotonic()
    phone_bus.publish({"type": "call_started", "call_id": call_id, "from": From})
    return _xml(_twiml(turn, call_id))


@router.post("/gather")
async def gather(
    CallSid: str = Form(...),
    Digits:  str = Form(default=""),
    SpeechResult: str = Form(default=""),
):
    """
    Single entry point for all caller input on the Twilio side.

    <Gather> can send back:
      - Digits            → keypad press → on_digit
      - SpeechResult      → speech transcript → on_chat or on_speech
      - Neither (timeout) → treat as silence, re-render the current turn or
        fall back to a fresh session
    """
    call_id = _CALL_MAP.get(CallSid)
    if not call_id:
        call_id, turn = begin()
        _CALL_MAP[CallSid]   = call_id
        _CALL_START[CallSid] = time.monotonic()
        return _xml(_twiml(turn, call_id))

    if Digits:
        turn = on_digit(call_id, Digits)
    elif SpeechResult:
        session = _SESSIONS.get(call_id)
        handler = on_chat if session and session.state == "chatting" else on_speech
        turn = handler(call_id, SpeechResult)
    else:
        # Timeout with nothing captured — bounce them back to speak again.
        turn = on_speech(call_id, "")

    return _xml(_twiml(turn, call_id))


@router.post("/speech")
async def speech_legacy(
    CallSid: str = Form(...),
    SpeechResult: str = Form(default=""),
):
    """
    Legacy endpoint. Old TwiML used <Record> and posted RecordingUrl here;
    trial accounts can't use <Record> so nothing new hits this. Kept as a
    thin forward in case any Twilio queue still has a stale action URL.
    """
    call_id = _CALL_MAP.get(CallSid)
    if not call_id:
        call_id, turn = begin()
        _CALL_MAP[CallSid] = call_id
        return _xml(_twiml(turn, call_id))

    session = _SESSIONS.get(call_id)
    handler = on_chat if session and session.state == "chatting" else on_speech
    turn = handler(call_id, SpeechResult)
    return _xml(_twiml(turn, call_id))


@router.post("/status")
async def status(
    CallSid:    str = Form(...),
    CallStatus: str = Form(default=""),
    From:       str = Form(default=""),
    CallDuration: str = Form(default="0"),
):
    """
    Twilio status callback — fires when a call ends for any reason.

    MISSED-CALL DETECTION:
      A genuine missed call has duration ≤ MISSED_CALL_MAX_DURATION seconds
      and status "completed" or "no-answer". We call the user back immediately
      in a background thread so this endpoint returns in <100ms.

    We also clean up in-memory session state.
    """
    duration = int(CallDuration or 0)
    start    = _CALL_START.get(CallSid)
    elapsed  = (time.monotonic() - start) if start else duration

    is_missed = (
        CallStatus in ("completed", "no-answer")
        and elapsed <= MISSED_CALL_MAX_DURATION
        and From                          # we have a number to call back
        and CallSid not in _CALL_MAP      # session never got past greeting
                                          # (if it did, they stayed on the line)
    )

    if is_missed:
        log.info("Missed call from %s (duration %ss) — calling back", From, duration)
        threading.Thread(target=_call_back, args=(From,), daemon=True).start()

    # Clean up
    call_id = _CALL_MAP.pop(CallSid, None)
    _CALL_START.pop(CallSid, None)

    phone_bus.publish({"type": "call_ended", "call_id": call_id, "missed": is_missed})

    return Response(content="", status_code=204)
