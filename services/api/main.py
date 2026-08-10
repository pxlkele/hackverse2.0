"""
Setu API.

    .venv/bin/uvicorn services.api.main:app --reload --port 8000

Endpoints exist so the dashboard can render the full chain:
    text -> profile -> retrieved chunks -> decisions -> citations
"""

from __future__ import annotations

import os
import shutil
import tempfile
import time
import uuid
from pathlib import Path

from dotenv import load_dotenv

# Load .env before importing any module that reads env at import time
# (channels.twilio_webhook captures PUBLIC_URL / TWILIO_* on import;
# voice.py captures VOICE_MODE). override=True so edits to .env win over
# whatever was in the shell env when uvicorn was started.
load_dotenv(override=True)

import asyncio
import json

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import PlainTextResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .core import (
    doc_doctor, eligibility, ledger, llm, narrate, pathfinder,
    phone_bus, profile as profile_mod, rag, store, voice,
)
from pydantic import BaseModel

from .core.schemas import Profile, QueryRequest, QueryResponse, TrustTrace

app = FastAPI(title="Setu API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # hackathon; tighten before any real deployment
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def _warm_models() -> None:
    """
    Preload Granite so the first judge-facing query isn't the slow one, and
    Whisper so the first *spoken* one isn't either — measured at ~10s of weight
    loading that the caller's first tap would otherwise pay on stage.

    Deliberately blocking: this costs startup time we have plenty of and buys
    silence-free latency we do not. Start the server before the demo, not
    during it.
    """
    llm.warm()
    voice.warm()

    # The vision model is 2.4GB resident. On a laptop already holding Granite,
    # Whisper small and (for Telugu and Kannada) Whisper medium, keeping it
    # loaded is what turns a steady 6s answer into an erratic one: the same
    # hi.mp3 measured asr=6.4s on one request and asr=52.9s on another, with
    # nothing else running and a load average above 8. Set SETU_WARM=voice for
    # a voice-only demo and the document checker still works, it just pays its
    # ~47s cold start on first use. Default is unchanged.
    if os.getenv("SETU_WARM", "all") != "voice":
        doc_doctor.warm()   # 2.4GB vision model: ~47s cold, ~3.5s warm


@app.get("/api/health")
def health():
    """Everything the pre-flight checklist needs in one call."""
    return {"llm": llm.health(), "index": rag.stats()}


@app.post("/api/extract", response_model=Profile)
def extract(request: QueryRequest):
    """Text -> structured Profile. No decisions made here."""
    try:
        return profile_mod.extract(request.text, language=request.language)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"extraction failed: {exc}") from exc


@app.get("/api/search")
def search(q: str, k: int = 5, scheme_id: str | None = None):
    """Raw retrieval — mainly for the dashboard and for debugging citations."""
    return {"query": q, "results": rag.search(q, k=k, scheme_id=scheme_id)}


@app.post("/api/query", response_model=QueryResponse)
def query(request: QueryRequest):
    """
    The full chain.

    Eligibility is not wired in yet — that arrives with eligibility.py and
    pathfinder.py. Until then this returns the profile and the retrieval, which
    is exactly what the dashboard needs to be built against.
    """
    timings: dict[str, float] = {}

    start = time.perf_counter()
    user_profile = profile_mod.extract(request.text, language=request.language)
    timings["extract_ms"] = round((time.perf_counter() - start) * 1000, 1)

    start = time.perf_counter()
    search_text = " ".join(
        part
        for part in [user_profile.occupation, user_profile.stated_need, request.text[:200]]
        if part
    )
    retrieved = rag.search(search_text, k=6)
    timings["retrieve_ms"] = round((time.perf_counter() - start) * 1000, 1)

    start = time.perf_counter()
    decisions = pathfinder.build_all(user_profile, eligibility.evaluate_all(user_profile))
    timings["decide_ms"] = round((time.perf_counter() - start) * 1000, 1)

    trace = TrustTrace(
        query_id=str(uuid.uuid4())[:8],
        profile=user_profile,
        retrieved_chunk_ids=[c.chunk_id for c in retrieved],
        decisions=decisions,
        schemes_version=eligibility.schemes_version(),
    )

    store.log_query(
        query_id=trace.query_id,
        user_id=request.user_id,
        text=request.text,
        language=request.language,
        profile=user_profile,
        decisions=decisions,
        fingerprint=trace.fingerprint(),
    )

    return QueryResponse(
        query_id=trace.query_id,
        profile=user_profile,
        missing_fields=profile_mod.missing_for_eligibility(user_profile),
        retrieved=retrieved,
        decisions=decisions,
        trace_fingerprint=trace.fingerprint(),
        timings_ms=timings,
        debug={
            "ladders_verified": {
                d.scheme_id: pathfinder.verify_ladder(user_profile, d)
                for d in decisions
                if d.ladder
            }
        },
    )



# ── Case store / dashboard endpoints (ported from Sanvi's agent.py) ──────────

@app.get("/api/stats")
def stats():
    return store.stats()


@app.get("/api/logs")
def logs(limit: int = 50):
    return store.recent_queries(limit)


@app.get("/api/gaps")
def gaps(limit: int = 50):
    """Unmatched needs — the Demand Signal."""
    return store.coverage_gaps(limit)


@app.post("/api/cases/{scheme_id}")
def start_case(scheme_id: str, request: QueryRequest, user_id: str = "demo"):
    """Turn a ladder into tracked commitments with due dates."""
    user_profile = profile_mod.extract(request.text, language=request.language)
    decisions = pathfinder.build_all(user_profile, eligibility.evaluate_all(user_profile))
    target = next((d for d in decisions if d.scheme_id == scheme_id), None)
    if not target:
        raise HTTPException(status_code=404, detail=f"no decision for {scheme_id}")
    return {"steps_created": store.open_case(user_id, target)}


@app.get("/api/cases/due")
def cases_due(as_of: str | None = None):
    """as_of lets the demo time-warp without waiting days."""
    return store.due_cases(as_of)


@app.post("/api/reason")
def reason(request: QueryRequest):
    """
    The full chain plus the visible thought process and a spoken answer.

    This is what the demo screen calls: it returns the real rule evaluations in
    order so the UI can reveal them one at a time, then the audio to play.
    """
    timings: dict[str, float] = {}

    start = time.perf_counter()
    user_profile = profile_mod.extract(request.text, language=request.language)
    timings["extract_ms"] = round((time.perf_counter() - start) * 1000, 1)

    start = time.perf_counter()
    decisions = pathfinder.build_all(user_profile, eligibility.evaluate_all(user_profile))
    timings["decide_ms"] = round((time.perf_counter() - start) * 1000, 1)

    start = time.perf_counter()
    spoken = narrate.narrate_all(user_profile, decisions, request.language)
    timings["narrate_ms"] = round((time.perf_counter() - start) * 1000, 1)

    audio_path = None
    try:
        audio_path = str(voice.speak(spoken, request.language))
    except voice.VoiceError:
        pass  # text still shows; never let TTS failure kill the answer

    trace = TrustTrace(
        query_id=str(uuid.uuid4())[:8],
        profile=user_profile,
        decisions=decisions,
        schemes_version=eligibility.schemes_version(),
    )
    store.log_query(
        query_id=trace.query_id, user_id=request.user_id, text=request.text,
        language=request.language, profile=user_profile, decisions=decisions,
        fingerprint=trace.fingerprint(),
    )

    return {
        "query_id": trace.query_id,
        "profile": user_profile.model_dump(mode="json"),
        "steps": narrate.reasoning_steps(user_profile, decisions),
        "decisions": [d.model_dump(mode="json") for d in decisions],
        "spoken_text": spoken,
        "audio_path": audio_path,
        "trace_fingerprint": trace.fingerprint(),
        "timings_ms": timings,
    }


@app.post("/api/documents/check")
async def check_documents(files: list[UploadFile] = File(...)):
    """
    Upload two or more document photos; get back what would cause a rejection.

    Filenames carry the type hint where possible (aadhaar.jpg, passbook.png) so
    the report can name the documents the way the user would.
    """
    if len(files) < 2:
        raise HTTPException(
            status_code=400,
            detail="Upload at least two documents — the check is a comparison.",
        )

    tmpdir = Path(tempfile.mkdtemp(prefix="setu_docs_"))
    paths: list[tuple[Path, str | None]] = []
    try:
        for upload in files:
            dest = tmpdir / (upload.filename or "document")
            dest.write_bytes(await upload.read())
            stem = dest.stem.lower()
            hint = next(
                (k for k in doc_doctor.DOC_LABELS if k.split("_")[0] in stem),
                None,
            )
            paths.append((dest, hint))
        return doc_doctor.review(paths)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


@app.get("/api/documents/health")
def documents_health():
    return {
        "vision_model": doc_doctor.VISION_MODEL,
        "vision_available": doc_doctor.vision_available(),
        "fallback": "docling OCR + granite",
    }


# ── Voice Ledger ────────────────────────────────────────────────────────────

class LedgerEntry(BaseModel):
    text: str
    user_id: str = "demo"
    on: str | None = None   # ISO date; defaults to today


@app.post("/api/ledger/entry")
def ledger_entry(request: LedgerEntry):
    """One evening's spoken takings."""
    from datetime import date as _date

    on = _date.fromisoformat(request.on) if request.on else None
    entry = ledger.record(request.user_id, request.text, on=on)
    return {
        "date": entry.on.isoformat(),
        "earned": entry.earned,
        "spent": entry.spent,
        "heard": entry.raw_text,
    }


@app.get("/api/ledger/statement")
def ledger_statement(user_id: str = "demo", days: int = 30, as_text: bool = False):
    """
    The cash-flow statement.

    as_text returns the plain-text version a lender would be handed, in which
    the provenance block sits above the totals on purpose.
    """
    statement = ledger.build_statement(user_id, days=days)
    if as_text:
        return PlainTextResponse(ledger.render_text(statement))
    return ledger.statement_dict(statement)


@app.post("/api/ledger/seed")
def ledger_seed(user_id: str = "demo", days: int = 30):
    """Thirty days of plausible takings, so the statement can be shown without
    waiting a month. Clearly a demo affordance, not a product feature."""
    written = ledger.seed_demo(user_id, days=days)
    return {"days_written": written, "user_id": user_id}


# ── Fairness / evaluation endpoints ─────────────────────────────────────────
#
# The claim is not "outcomes are balanced across groups" — that is only true
# because the persona set makes it so. The stronger claim is "the rule engine
# cannot see protected attributes at all." /api/eval/summary returns that audit
# plus per-slice match rates. /api/eval/flip_test lets a caller mutate one
# attribute on a persona and prove the decisions are byte-identical.

class FlipTestRequest(BaseModel):
    persona_id: str = "ramesh_no_cov"
    attribute: str = "gender"           # gender | state
    value_b: str = "female"             # value to flip TO


@app.get("/api/eval/summary")
def eval_summary():
    """
    One call for the Fairness tab.

    Runs the eval harness in-process (no LLM, pure Python, milliseconds) and
    returns the rule-field audit, per-slice match rates, per-scheme
    precision/recall/F1, and latency percentiles.
    """
    from eval.run_eval import evaluate_persona, fairness, load_personas, score

    personas = load_personas()
    results = [evaluate_persona(p) for p in personas]
    scores = score(results)
    fair = fairness(results)

    latencies = sorted(r["latency_ms"] for r in results)
    n = len(latencies)
    percentile = lambda p: latencies[min(int(n * p), n - 1)] if n else 0.0

    passed = sum(r["passed"] for r in results)
    macro_p = sum(s["precision"] for s in scores.values()) / len(scores) if scores else 0.0
    macro_r = sum(s["recall"] for s in scores.values()) / len(scores) if scores else 0.0

    return {
        "personas": len(personas),
        "passed": passed,
        "schemes_version": eligibility.schemes_version(),
        "rule_audit": eligibility.rule_field_audit(),
        "fairness": fair,
        "scores": scores,
        "macro": {"precision": round(macro_p, 3), "recall": round(macro_r, 3)},
        "latency_ms": {
            "median": round(percentile(0.5), 1),
            "p95": round(percentile(0.95), 1),
        },
    }


@app.post("/api/eval/flip_test")
def flip_test(request: FlipTestRequest):
    """
    Mutate one attribute on a persona, re-run the engine, and prove the
    decisions are byte-identical. The strongest possible answer to "how do you
    know it isn't biased" is a live demonstration that the model can't be —
    because the attribute is not in any rule.
    """
    import hashlib as _hashlib
    import json as _json

    from eval.run_eval import load_personas

    personas = {p["id"]: p for p in load_personas()}
    persona = personas.get(request.persona_id)
    if not persona:
        raise HTTPException(status_code=404, detail=f"no persona {request.persona_id!r}")

    profile_a = profile_mod.Profile(**persona["profile"])
    value_a = getattr(profile_a, request.attribute, None)

    if value_a is None:
        default = {"gender": "male", "state": persona["profile"].get("state", "Karnataka")}
        value_a = default.get(request.attribute, "unknown")
        profile_a = profile_a.model_copy(update={request.attribute: value_a})

    profile_b = profile_a.model_copy(update={request.attribute: request.value_b})

    def decide(p):
        return pathfinder.build_all(p, eligibility.evaluate_all(p))

    def dhash(ds):
        payload = _json.dumps(
            [d.model_dump(exclude={"explanation"}, mode="json") for d in ds],
            sort_keys=True, default=str,
        )
        return _hashlib.sha256(payload.encode()).hexdigest()[:16]

    decisions_a = decide(profile_a)
    decisions_b = decide(profile_b)
    hash_a, hash_b = dhash(decisions_a), dhash(decisions_b)

    return {
        "persona_id": request.persona_id,
        "attribute": request.attribute,
        "value_a": value_a,
        "value_b": request.value_b,
        "hash_a": hash_a,
        "hash_b": hash_b,
        "identical": hash_a == hash_b,
        "summary_a": {d.scheme_id: d.status.value for d in decisions_a},
        "summary_b": {d.scheme_id: d.status.value for d in decisions_b},
    }


@app.get("/api/audio")
def audio(path: str):
    """
    Serve a cached audio file to the console.

    Restricted to the voice cache directory: `path` arrives from a query string,
    so without the containment check any file on disk could be read.
    """
    from fastapi.responses import FileResponse

    resolved = Path(path).resolve()
    cache = voice.CACHE_DIR.resolve()
    if not resolved.is_file() or cache not in resolved.parents:
        raise HTTPException(status_code=404, detail="no such audio")
    return FileResponse(resolved, media_type="audio/mpeg")


@app.get("/api/voice/health")
def voice_health():
    return voice.cache_stats()


@app.get("/api/phone/stream")
async def phone_stream():
    """SSE stream of phone events (call start, user_speech transcripts, call end).
    The console subscribes to mirror the caller's transcript into its input."""
    q = phone_bus.subscribe()

    async def gen():
        try:
            yield ": connected\n\n"
            while True:
                try:
                    event = await asyncio.wait_for(q.get(), timeout=15.0)
                    yield f"data: {json.dumps(event)}\n\n"
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"  # keeps proxies from closing idle streams
        finally:
            phone_bus.unsubscribe(q)

    return StreamingResponse(gen(), media_type="text/event-stream")


# IVR simulator — browser keypad transport
from channels.ivr_sim import router as ivr_router  # noqa: E402
app.include_router(ivr_router)

# Vendor PWA — served from the same origin so relative /api/ivr/* calls work
# and so mic access is on HTTPS when reached via ngrok.
_PWA_DIR = Path(__file__).resolve().parents[2] / "apps" / "web" / "pwa"
if _PWA_DIR.exists():
    app.mount("/pwa", StaticFiles(directory=str(_PWA_DIR), html=True), name="pwa")

# Twilio webhook — real phone calls through the same state machine
from channels.twilio_webhook import router as twilio_router  # noqa: E402
app.include_router(twilio_router)


# Mounted last: a mount at "/" swallows every route declared after it.
# Console (React build) is the primary UI — served at /.
# The static pipeline page is kept at /demo/ as a fallback that works offline.
CONSOLE = Path(__file__).resolve().parent.parent.parent / "apps" / "console" / "dist"
WEB = Path(__file__).resolve().parent.parent.parent / "apps" / "web"

if CONSOLE.exists():
    app.mount("/", StaticFiles(directory=str(CONSOLE), html=True), name="console")
elif WEB.exists():
    app.mount("/", StaticFiles(directory=str(WEB), html=True), name="web")
