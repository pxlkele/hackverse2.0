# Setu — Work Split (2 people)

**Palak = the brain** (data, rules, decisions)
**Sanvi = the surface** (LLM plumbing, dashboard, UI, voice)

Swap if your strengths run the other way — but decide once, now, and don't
renegotiate at hour 20.

---

## First, the honest math

Two people × ~30 working hours = **60 person-hours**. The P0 core alone is
roughly 40 of those. So the three-person plan doesn't fit, and pretending it
does is how you end up at hour 34 with six half-features and no demo.

**Cuts made for two people:**

| Cut | Why |
|---|---|
| 6 schemes → **4** | PM SVANidhi, FSSAI, e-Shram, PMSBY. SVANidhi is the anchor; the rest give breadth on the dashboard |
| Real Twilio telephony → **simulator only** | Saves 3–4 hrs. Identical code path, judges can't tell |
| WhatsApp → **cut** | Nice-to-have, not a differentiator |
| Doc Doctor **or** Voice Ledger → **pick one** | Both is ~11 hrs you don't have. Decide at hour 22 based on what the field session gave you |
| Fairness audit: 4 slices → **2** | Still scores the governance point |
| Fraud Shield, Demand Signal → **roadmap slide** | Talk about them, don't build them |

**What you're actually shipping:** real user footage → voice input → **the
ladder** → one depth feature → IVR simulator → dashboard. That's a winning demo.
Five moments, not seven.

---

## Hours 0–2 — TOGETHER *(mostly done)*

- [x] Scaffold, `.gitignore`, `.env.example`, schemas frozen
- [ ] 4 scheme PDFs in `ingestion/sources/`
- [ ] Ollama verified (Palak) · Whisper + edge-tts verified (Sanvi)
- [ ] First commit pushed

**Also: book the vendor field session for hour 4–6.** It gates the ASR test set
and `schemes.yaml`. Do not let this slide to hour 20.

---

## Hours 2–10 — THE BRAIN 🚦

Nothing touches a microphone in this block.

| | **PALAK** | **SANVI** |
|---|---|---|
| **2–5** | `ingestion/pipeline.py` — Docling → DPK chunk + PII-redact → `granite-embedding:278m` → Chroma. Commit the index. | `core/llm.py` — Granite adapter, JSON/tool-call mode, retry-on-invalid-JSON. Then `core/profile.py` — **typed text** → Profile JSON. |
| **5–10** | `data/schemes.yaml` for 4 schemes + `core/eligibility.py` with unit tests. Every rule carries `source_doc`, `source_span`, **and `remedy`** (fix, ₹ cost, days). | Dev dashboard — renders the whole chain: query → retrieved chunks → rules fired → decision → citation. Plain HTML is fine. This is your debugging tool. |

> **🚦 GATE AT HOUR 10.** Type a paragraph about a street vendor into a box, get
> back a correct decision with a real citation from the PM SVANidhi PDF, visible
> in Sanvi's dashboard. **If this fails, cut schemes until it passes.** Everything
> after assumes it.

---

## Hours 10–16 — THE LADDER ★

| | |
|---|---|
| **PALAK** | `core/pathfinder.py` — minimal-mutation search → ranked ladder, each step costed in ₹ and days. **This is the centrepiece of the entire project.** Then `core/rag.py` citation resolution. |
| **SANVI** | **Ladder view** — the hero screen. Steps as a climbable path, each with cost/time/"do this now", plus a "Why?" expander showing the rule and the PDF snippet. |

At hour 16 you should be able to demo moments 1 and 2. That's already a
submission. Everything past here is upside.

---

## Hours 16–22 — Proof + Voice IN

| | |
|---|---|
| **PALAK** | `core/trust.py` replayable traces + `eval/` with **20 personas** and a 2-slice fairness audit. Get a real precision number. |
| **SANVI** | PWA shell for real users (giant buttons, icons over text, every control speaks itself) + **voice IN**: mic → faster-whisper → the pipeline you already trust. |

**Sanvi: pre-cache the demo audio the moment ASR works.** Single strongest
insurance policy in the build.

---

## Hours 22–28 — Pick ONE depth feature

Decide together at hour 22. **Do not attempt both.**

**Option A — Document Doctor** *(pick this if the vendor's documents actually
have a name mismatch)*
- Palak: `doc_doctor.py` — field extraction + cross-document comparison
- Sanvi: camera capture flow + the "this would have been rejected" result UI

**Option B — Voice Ledger / Trust Passport** *(pick this if his documents are
clean, or if you got UPI data)*
- Palak: `ledger.py` — aggregation → cash-flow PDF with `provenance`,
  `days_covered`, `corroboration_pct` as first-class fields
- Sanvi: daily-prompt UI, trend chart, "generate my statement" button

Also in this block: **Sanvi** wires voice OUT (edge-tts) — 1 hour, do it first.

---

## Hours 28–32 — Integration *(together)*

- Wire everything to one core; fix the seams
- Seed `setu.db` with 5 personas at different stages so it looks lived-in
- `standing.py` — catalog-change re-evaluation (Palak, ~2 hrs, cheap and impressive)
- IVR simulator in the browser (Sanvi, ~2 hrs)
- Timeouts + cached fallbacks on every external call
- **Kill the wifi and run the whole demo.** If anything breaks, it isn't done.

---

## Hours 32–36 — Buffer. **Nothing new.**

- Record the backup video **at hour 32**, while things work
- Finalise `DEMO_SCRIPT.md` with real numbers and real screenshots
- Rebuild the deck around the reframe
- Rehearse out loud, twice, timed, with the laptop
- If you're tempted to add a feature here: don't

---

## Who owns what, at a glance

**PALAK — the brain**
```
ingestion/pipeline.py      Docling → DPK → Chroma
data/schemes.yaml          typed rules + remedies  ← highest-value artifact
core/eligibility.py        the rule engine
core/pathfinder.py         the ladder  ★
core/rag.py                citations
core/trust.py              replayable traces
core/standing.py           re-evaluation
eval/                      personas, precision, fairness
ledger.py OR doc_doctor.py logic half
```

**SANVI — the surface**
```
core/llm.py                Granite adapter
core/profile.py            text → Profile JSON
core/voice.py              Whisper in, edge-tts out
apps/web/dashboard         dev tool, built early
apps/web/ladder            THE HERO SCREEN  ★
apps/web/pwa               real-user interface
channels/ivr_sim.py        browser IVR
ledger.py OR doc_doctor.py UI half
```

---

## Rules for two people

1. **The hour-10 gate is a full stop.** Neither of you moves past it until a
   typed paragraph returns a cited decision.
2. **Merge to `main` every 3 hours minimum.** Two people diverging for 8 hours
   is a guaranteed integration disaster at hour 28.
3. **The frozen schemas are frozen.** If one of you needs a change, both stop and
   agree. Silent schema edits will cost you hours.
4. **If you fall behind, cut schemes first** — 3 schemes with a working ladder
   beats 4 with a broken one.
5. **Ladder before everything.** If it comes down to the ladder or any other
   feature, the ladder wins. It's the whole submission.
6. **Sleep in shifts if you must, but don't both go under at once.** One person
   awake and coherent beats two people making 3am decisions.
