# Setu — Operator Console

The screen a CSC operator or Bank Mitra sees while helping someone. The vendor
never looks at it; he only hears the audio at the end.

Designed in Figma Make, then rewired onto the real pipeline.

## Running it

Two processes. The API must be up first — it warms Granite, Whisper and the
vision model on startup, which takes a minute and is the difference between a
3-second demo and a 45-second one.

```sh
# terminal 1 — the engine
.venv/bin/uvicorn services.api.main:app --port 8000

# terminal 2 — the console
cd apps/console && npm install && npm run dev
```

Then open http://localhost:5173. Vite proxies `/api` to port 8000.

## What the three stages show

| Stage | Source |
|---|---|
| 01 Input & Understanding | `profile.extract()` — only fields the person actually stated, with anything we derived listed separately |
| 02 Retrieval & Matching | every rule that fired, PASS/FAIL/unknown, each with the government document and page |
| 03 Response & Outcome | the decision, the costed ladder out of it, the real trace fingerprint and real latency |

## What was changed from the export

The Figma export simulated the pipeline: `await pause(2800)` followed by
hardcoded strings — invented rule names (`rule_001 greeting_protocol`), invented
chunk ids, a `sentiment 0.72` score and a `confidence 0.94` the system does not
produce.

All of it now comes from `POST /api/reason`. The staged reveal was kept, because
a human needs a beat to read each line, but the *content* is real: every tick is
a rule that actually fired, every citation resolves to a verbatim quote on the
page it names, and the latency shown is the latency measured.

That distinction is the whole pitch. Pacing a reveal is presentation; inventing
the content would be a lie, and a judge who asks "is this real?" deserves a
demonstration rather than an assurance — type a different vendor and watch
different boxes tick.
