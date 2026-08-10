# Setu — Making Invisible People Underwritable

**Setu is a voice-first AI assistant that walks informal-sector workers from
what they said, in their own language, to the government schemes they qualify
for and the exact next step to take.**

Built for **IBM HackVerse 2.0** by [Palak Patnaik](https://github.com/pxlke) and
[Sanvi](https://github.com/sanvi2006-coder).

---

## Why

- **400M+ Indians** work in the informal sector — vendors, tailors, farmers,
  auto-drivers, rickshaw pullers.
- The government has **40+ welfare schemes** for them: insurance, loans,
  pension, food licences.
- Almost none of those Indians know which schemes they qualify for. Forms are
  in English, portals assume a smartphone, and a Bank Mitra explaining
  eligibility to one vendor takes **two hours**.

Setu takes fifteen seconds. The vendor speaks; Setu responds — grounded in
real government PDFs, spoken back in the language they used.

---

## Live demo

- **Operator console (dashboard):** deployed on Vercel — see the deployment on
  the project's GitHub for the current URL.
- **Vendor PWA:** `<ngrok-url>/pwa/` — served from the same backend the
  console talks to.

Open the PWA on a phone, pick a language, tap the green mic. The mic requires
HTTPS (`getUserMedia` refuses `http://`) — that's why everything runs behind a
tunnel.

The tunnel URL is temporary. To regenerate:

```bash
.venv/bin/uvicorn services.api.main:app --host 0.0.0.0 --port 8000
ngrok http --domain=<your-reserved-domain> 8000        # or:
cloudflared tunnel --url http://localhost:8000
```

Give the server ~60 seconds after start before demoing — it warms Whisper and
Ollama in the background.

---

## What it does

### Three channels, one pipeline

| Channel | Best for | How it reaches Setu |
|---|---|---|
| **PWA** (`apps/web/pwa/`) | Vendors with a smartphone + data | Browser mic, plays TTS response |
| **Twilio phone** (`channels/twilio_webhook.py`) | Feature-phone users | Missed call → automated callback → IVR conversation |
| **Operator console** (`apps/console/`) | Bank Mitras / CSC operators | Types on the vendor's behalf, watches the pipeline live |

All three feed into `channels/ivr_sim.py` — one state machine, one set of
prompts, one narration pipeline. The PWA/phone/console differences are just
transport.

### The pipeline (three visible stages)

1. **Input & Understanding** — Whisper transcribes speech → Granite structures
   it into a `Profile` (age, occupation, income, documents, city).
2. **Retrieval & Matching** — deterministic rule engine over `schemes.yaml`
   evaluates every scheme. Each rule cites the exact page + verbatim quote from
   the government PDF that established it.
3. **Response & Outcome** — pathfinder builds a "ladder" of concrete steps
   (open a bank account, get a vending certificate). Granite narrates the
   answer in the caller's language; edge-tts speaks it back.

### After the answer: chat

Once the initial answer plays, the mic stays open. The vendor can ask
follow-ups — *"which documents?", "where do I go?", "how long does it take?"* —
and the LLM answers, **grounded** in the schemes it already told them about.
The prompt hard-constrains it to never invent a scheme or an amount.

### Two more tabs

- **Doc Doctor** — vision reads the vendor's Aadhaar / bank passbook / vending
  certificate, catches mismatches (name spelt differently across docs, expired
  IDs) that would bounce an application.
- **Voice Ledger** — the vendor spends five seconds a night saying today's
  earnings. Thirty days later → a bank-readable cash-flow statement that
  unlocks the PM SVANidhi loan Setu told them about at the start.

### Fairness by construction

Charts in `eval/out/fairness/` — 21 personas × 11 states × both genders ×
urban/rural. Match rate: **100% across every slice**. Not because we tuned it:
because gender, state, and rural/urban aren't inputs to any rule. The audit
proves the invariant hasn't drifted.

```bash
.venv/bin/python eval/fairness_charts.py
```

---

## Languages

Hindi, English, Marathi, Gujarati, Bengali, Tamil, Telugu, Kannada.

`GET /api/ivr/languages` is the authoritative list and reports, per language,
whether its prompts speak offline. Real ASR transcripts for each language are
checked in as tests (`services/api/tests/test_profile.py`).

Notes:
- Whisper transcribes Gujarati / Bengali / Telugu **in Devanagari** phonetically.
  Judge a language by whether age + income + occupation are extracted, not by
  script fidelity.
- Telugu and Kannada require Whisper `medium` (see `voice.ASR_MODEL_FOR`);
  Kannada takes ~90 s uncached — pre-cache before demo.

---

## Local setup

```bash
# 1. Backend
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env       # fill in TWILIO_*, PUBLIC_URL, VOICE_MODE

# 2. Ollama with Granite (LLM) + Granite Embeddings (RAG)
ollama pull granite4:tiny-h
ollama pull granite-embedding:278m

# 3. Warm the caches — do this before every demo
.venv/bin/python eval/precache_narrations.py            # all 8 languages
.venv/bin/python eval/precache_narrations.py hi en mr   # just three

# 4. Run
.venv/bin/uvicorn services.api.main:app --host 0.0.0.0 --port 8000

# 5. Console (dev)
cd apps/console && npm install && npm run dev
```

---

## Architecture

```
┌───────────────────┐    ┌───────────────────┐    ┌───────────────────┐
│   PWA (phone)     │    │  Twilio callback  │    │  Console (React)  │
│  apps/web/pwa/    │    │ channels/twilio_  │    │   apps/console/   │
└─────────┬─────────┘    └─────────┬─────────┘    └─────────┬─────────┘
          │                        │                        │
          └────────────┬───────────┴────────────┬───────────┘
                       │                        │
                       ▼                        ▼
              ┌────────────────┐        ┌───────────────┐
              │ channels/      │        │  phone_bus    │
              │ ivr_sim.py     │◀───────│  (SSE mirror) │
              │  begin/        │        └───────────────┘
              │  on_speech/    │
              │  on_chat/      │
              │  on_digit      │
              └───────┬────────┘
                      │
       ┌──────────────┼──────────────┬──────────────┐
       ▼              ▼              ▼              ▼
   ┌───────┐     ┌─────────┐    ┌───────────┐  ┌──────┐
   │ voice │     │ profile │    │eligibility│  │narrate│
   │  (asr │     │(extract │    │ + path-   │  │ + TTS │
   │  +tts)│     │  → JSON)│    │  finder)  │  │       │
   └───┬───┘     └────┬────┘    └─────┬─────┘  └───┬───┘
       │              │               │            │
   Whisper          Granite       schemes.yaml   Granite
   edge-tts       (chat_json)     (rule engine)  edge-tts
```

Everything on the right of the dotted line is local — Whisper, Granite,
edge-tts, ChromaDB. Backend has no cloud dependency; a fresh clone answers a
question with the wifi off, provided the caches are warm.

---

## Tech stack

- **Backend:** FastAPI + Uvicorn
- **LLM:** IBM Granite (`granite4:tiny-h`) via Ollama
- **Embeddings:** `granite-embedding:278m`
- **ASR:** faster-whisper (small / medium)
- **TTS:** edge-tts (Microsoft neural voices, Indic)
- **RAG:** ChromaDB with content-hashed cache
- **Frontend:** React + Vite + Tailwind (console); vanilla HTML + service
  worker (PWA)
- **Tunnels:** ngrok (dev) / cloudflared (alternative)
- **Telephony:** Twilio Voice
- **Deployment:** Vercel (console frontend), backend on developer laptop with
  tunnel

---

## Team

| Palak Patnaik (`@pxlkele`) | Sanvi (`@sanvi2006-coder`) |
|---|---|
| Operator console + landing hero | Vendor PWA (8 languages) |
| Twilio phone channel + missed-call callback | Whisper ASR calibration, `_run_blocking` fix |
| Phone/PWA → console live SSE mirror | Granite narration in 8 languages |
| LLM follow-up chat mode | Answer-in-caller's-language guard |
| Voice Ledger, Doc Doctor | Precache script (offline demo) |
| Fairness audit + charts | Deterministic-layer bug fixes |
| Vercel deployment | Cloudflared tunnel + docs |

---

## Repo hygiene

Three tracked files rewrite themselves just from running the app; don't commit
them:

```bash
git checkout -- services/api/data/chroma/ services/api/data/setu.db
```

`chroma/*` gets rewritten by reads; `setu.db` grows a row every query.
Cached files under `voice_cache/`, `narration_cache/`, `profile_cache/`, and
`ui_cache/` are the opposite — they're deliberate, and they're what lets the
demo run with the wifi off. Commit those.

---

## License

See `LICENSE`.
