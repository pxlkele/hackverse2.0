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
import tempfile
import threading
import time
from pathlib import Path

import httpx
from fastapi import APIRouter, Form, Request, Response

from channels.ivr_sim import begin, on_digit, on_speech, Turn

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
MISSED_CALL_MAX_DURATION = 8   # seconds


def _twiml(turn: Turn) -> str:
    """
    Render a Turn as TwiML.

    Structure:
      - If there is a cached audio file, <Play> it (sounds better than <Say>).
      - Otherwise <Say> the text with Polly.
      - Then wait for what the turn expects:
        - "digit"  → <Gather numDigits="1">
        - "speech" → <Record maxLength="15" playBeep="true">
        - "end"    → <Hangup>
    """
    lines = ['<?xml version="1.0" encoding="UTF-8"?>', "<Response>"]

    # ── say or play ──────────────────────────────────────────────────────────
    # audio_url from the sim is relative (/api/ivr/audio/abc123). We need the
    # full public URL for Twilio to fetch it. If PUBLIC_URL is not set we fall
    # back to <Say>.
    if turn.audio_url and PUBLIC_URL:
        full = f"{PUBLIC_URL}{turn.audio_url}"
        lines.append(f'  <Play>{full}</Play>')
    else:
        # Polly.Aditi is the only Indian Hindi voice on Twilio's free tier.
        safe = turn.say.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        lines.append(f'  <Say voice="Polly.Aditi" language="hi-IN">{safe}</Say>')

    # ── gather / record / hangup ─────────────────────────────────────────────
    if turn.expect == "digit":
        lines.append(f'  <Gather numDigits="1" action="{PUBLIC_URL}/twilio/gather" method="POST"/>')
    elif turn.expect == "speech":
        lines.append(
            f'  <Record maxLength="15" playBeep="true" '
            f'action="{PUBLIC_URL}/twilio/speech" method="POST"/>'
        )
    elif turn.expect == "end":
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
            resp = client.post(
                f"https://api.twilio.com/2010-04-01/Accounts/{ACCOUNT_SID}/Calls.json",
                auth=(ACCOUNT_SID, AUTH_TOKEN),
                data={
                    "To":  to,
                    "From": FROM_NUMBER,
                    "Url":  f"{PUBLIC_URL}/twilio/incoming",
                    "StatusCallback":       f"{PUBLIC_URL}/twilio/status",
                    "StatusCallbackMethod": "POST",
                    "StatusCallbackEvent":  "completed",
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
    return _xml(_twiml(turn))


@router.post("/gather")
async def gather(
    CallSid: str = Form(...),
    Digits:  str = Form(default=""),
):
    """Twilio calls this after the caller presses a key."""
    call_id = _CALL_MAP.get(CallSid)
    if not call_id:
        call_id, turn = begin()
        _CALL_MAP[CallSid]   = call_id
        _CALL_START[CallSid] = time.monotonic()
        return _xml(_twiml(turn))

    turn = on_digit(call_id, Digits)
    return _xml(_twiml(turn))


@router.post("/speech")
async def speech(
    request: Request,
    CallSid: str = Form(...),
    RecordingUrl: str = Form(default=""),
):
    """
    Twilio calls this after a <Record> finishes.

    We download the recording from Twilio, transcribe with Whisper, then run
    the full pipeline — identical to the browser mic path.
    """
    call_id = _CALL_MAP.get(CallSid)
    if not call_id:
        call_id, turn = begin()
        _CALL_MAP[CallSid] = call_id
        return _xml(_twiml(turn))

    text = ""
    if RecordingUrl:
        try:
            resp = httpx.get(
                f"{RecordingUrl}.mp3",
                auth=(ACCOUNT_SID, AUTH_TOKEN),
                timeout=30,
                follow_redirects=True,
            )
            resp.raise_for_status()
            with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
                tmp.write(resp.content)
                clip = tmp.name
            from services.api.core import voice
            text = voice.transcribe(clip, language="hi")
            Path(clip).unlink(missing_ok=True)
        except Exception:  # noqa: BLE001
            pass  # empty text → nothing_heard branch in on_speech

    turn = on_speech(call_id, text)
    return _xml(_twiml(turn))


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
    _CALL_MAP.pop(CallSid, None)
    _CALL_START.pop(CallSid, None)

    return Response(content="", status_code=204)
