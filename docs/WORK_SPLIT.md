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
| **PALAK** | Replayable traces + `eval/` with **20 personas** and a 2-slice fairness audit. Get a real precision number. |
| **SANVI** | PWA shell for real users (giant buttons, icons over text, every control speaks itself) + **voice IN**: mic → faster-whisper → the pipeline you already trust. |

> *Shipped differently:* there is no `core/trust.py`, which an earlier version of
> this row named. The traces landed as `TrustTrace` in `core/schemas.py` behind
> `POST /api/reason`, and `eval/` ran **21** personas, not 20. Nothing is
> missing — that file just never existed, so don't go looking for it.

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
- ~~`standing.py` — catalog-change re-evaluation~~ **CUT** (see the bottom of
  this file; it never demoed as more than "trust us, it re-runs")
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

> **Revised mid-build.** Palak has taken over the operator console, so the split
> is no longer brain/surface — it is now **console + engine (Palak)** against
> **phone + channels (Sanvi)**. Split by *file*, not by layer, because two
> people editing the same UI file is how you lose an hour to conflicts at 3am.

**PALAK — engine and operator console**
```
ingestion/pipeline.py         Docling → DPK → Chroma            done
data/schemes.yaml             typed rules + remedies  ★         done, 4 schemes
core/eligibility.py           the rule engine                   done
core/pathfinder.py            the ladder  ★                     done
core/rag.py                   citations                         done
core/doc_doctor.py            document comparison               done
core/store.py                 cases, coverage gaps              done
eval/                         personas, fairness, citations     done
core/ledger.py                voice ledger → statement          TO BUILD
apps/dashboard/app.py         operator console — YOURS NOW      needs Doc Doctor
                              + ladder view + ledger view
```

**SANVI — phone and channels**
```
core/llm.py                   Granite adapter                   done
core/profile.py               text → Profile JSON               done
core/voice.py                 Whisper in, edge-tts out          done

the PWA — the vendor's own phone, served at /pwa/
apps/web/pwa/index.html       giant buttons, controls speak     done
apps/web/pwa/sw.js            offline shell                     done
apps/web/pwa/manifest.webmanifest  install to home screen       done
apps/web/pwa/icon-192.png     app icon                          done
apps/web/pwa/icon-512.png     app icon                          done

the IVR — feature-phone demo, served at /
channels/ivr_sim.py           IVR state machine + FastAPI router  done
apps/web/index.html           the handset UI (keypad, dial)      done
```

Two files make the IVR, not one: the router and the handset that drives it.
`apps/web/index.html` is the **IVR simulator**, not the PWA — an earlier version
of this table had that backwards and left the five `apps/web/pwa/` files with no
owner at all.

**File ownership is the rule.** Palak touches `apps/dashboard/`, Sanvi touches
`apps/web/` and `channels/`. Anything in `services/api/core/` either of you may
edit, but say so in chat first — that is where you will collide.

---

## Rules for two people

1. **The hour-10 gate is a full stop.** Neither of you moves past it until a
   typed paragraph returns a cited decision.
2. **Merge to `main` every 3 hours minimum.** Two people diverging for 8 hours
   is a guaranteed integration disaster at hour 28.
3. **The frozen schemas are frozen.** If one of you needs a change, both stop and
   agree. Silent schema edits will cost you hours.
   (Amended: `Profile`, `Decision` and `LadderStep` have all grown since hour 2 —
   age parsing, UPI documents, rung citations, `depends_on`. Each change was
   announced. Keep doing that.)
4. **If you fall behind, cut schemes first** — 3 schemes with a working ladder
   beats 4 with a broken one.
5. **Ladder before everything.** If it comes down to the ladder or any other
   feature, the ladder wins. It's the whole submission.
6. **Sleep in shifts if you must, but don't both go under at once.** One person
   awake and coherent beats two people making 3am decisions.

---

## Where it stands, and what is left

**Done:** ingestion with IBM Data Prep Kit (642 chunks, 9 documents), four
schemes with verbatim-verified citations, the eligibility engine, the ladder
with dependency ordering, Doc Doctor, the case store, the eval harness (21
personas, precision and recall 1.00, fairness spread 0.00), the citation
verifier, 69 tests, voice in and out, the operator console, the PWA and the IVR
simulator.

**Left — code**

| What | Owner | Est |
|---|---|---|
| Doc Doctor UI — the endpoint works but **nothing calls it** | Palak | ~1h |
| `core/ledger.py` + statement view | Palak | ~3h |

**Left — not code, and this is where the remaining risk is**

1. **Field session** — his voice, his documents, the name-spelling check.
   Curfew-gated. Everything else can be rehearsed; this cannot be faked.
2. **Airplane-mode run** — wifi off, the whole demo, end to end. Never done yet.
   It will find something, so do it while there is time to fix it.
3. **Backup video** — record while things work.
4. **Deck** — Round 1 still says ₹10k/₹20k/₹50k and claims Bhashini. The
   tranches are ₹15k/₹25k/₹50k and Bhashini is not in the stack. A judge
   cross-referencing the deck against the demo will read mismatches as
   sloppiness.
5. **Rehearse twice, out loud, timed.**

**Cut and staying cut:** `standing.py` (demos as "trust us, it re-runs" — put it
on the roadmap slide), real Twilio telephony, WhatsApp.
