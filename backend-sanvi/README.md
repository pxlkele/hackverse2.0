# Setu - build scaffold

Voice-first vernacular assistant for scheme/loan/insurance discovery.
Pipeline: docs -> Docling/chunk -> Chroma (RAG) -> Granite reasoning ->
agentic layer (log, profile, reminders) -> dashboard. Voice (AI4Bharat
ASR/TTS) plugs in around the same `/query` interface once this core is solid.

## 0. Before anything else

Replace the two `PLACEHOLDER_*.txt` files in `data/schemes/` with real,
verified government scheme PDFs (PMEGP, PMMY, PM-SVANidhi, state schemes,
whatever your persona needs). The placeholders exist only so you can smoke
test the pipeline today. Demoing on placeholder numbers contradicts the
"RAG-grounded, not hallucinated" pitch.

## 1. Setup

```bash
cd setu
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# edit .env: set HF_TOKEN to a Hugging Face token with access to the Granite model
```

## 2. Ingest scheme docs -> Chroma

```bash
python backend/ingest.py
```

Re-run any time you add/replace files in `data/schemes/`.

## 3. Sanity check RAG + Granite from the CLI (do this before the dashboard)

```bash
export HF_TOKEN=...   # or rely on .env if you wire python-dotenv in
python backend/rag.py "I run a tailoring shop, no loan history"
```

If `GRANITE_MODEL` 404s or rate-limits on the serverless Inference API, that's
your signal to switch to a dedicated HF Inference Endpoint - don't burn hours
debugging that later in the build.

## 4. Run the backend API

```bash
uvicorn backend.main:app --reload --port 8000
```

`POST /query {"user_id": "...", "text": "..."}` is the single entry point
voice will eventually call into.

## 5. Run the dashboard

```bash
streamlit run dashboard/app.py
```

This is your ops view: run queries, watch retrieval + Granite output, see the
query log and any due reminders. It's also your fallback demo screen if voice
isn't ready in time.

## Build order (see chat for full rationale)

1. Ingest real scheme docs, confirm retrieval quality.
2. Confirm Granite calls work end-to-end from the CLI.
3. Get the dashboard showing live queries against the real backend.
4. Layer in AI4Bharat ASR on the input side, then TTS on the output side.
5. IVR/WhatsApp wrapper only if time remains - first thing to cut.

## What's stubbed / needs a decision

- Embeddings currently use `sentence-transformers/all-MiniLM-L6-v2` locally
  (fast, no external dependency, no rate limits) rather than a Granite
  embedding endpoint. If matching your deck's exact claim of "Granite
  embeddings" matters for judges, swap this in `backend/rag.py` /
  `backend/ingest.py` - but know it adds another external-API failure point
  on demo day.
- Reminders are a simple `due_date <= today` SQLite flag, not a real
  scheduler/cron. Fine for a demo; say so if asked.
- No auth, no multi-tenant isolation - out of scope for a hackathon build.
