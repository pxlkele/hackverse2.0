"""
Setu API.

    .venv/bin/uvicorn services.api.main:app --reload --port 8000

Endpoints exist so the dashboard can render the full chain:
    text -> profile -> retrieved chunks -> decisions -> citations
"""

from __future__ import annotations

import time
import uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .core import eligibility, llm, narrate, pathfinder, profile as profile_mod, rag, store, voice
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
    """Preload Granite so the first judge-facing query isn't the slow one."""
    llm.warm()


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


@app.get("/api/voice/health")
def voice_health():
    return voice.cache_stats()


# Mounted last: a mount at "/" swallows every route declared after it.
WEB = Path(__file__).resolve().parent.parent.parent / "apps" / "web"
if WEB.exists():
    app.mount("/", StaticFiles(directory=str(WEB), html=True), name="web")
