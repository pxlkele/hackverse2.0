# Setu — Making Invisible People Underwritable

Setu is a voice-first AI assistant that walks informal-sector workers from
their current situation to government schemes they qualify for.

Built for IBM Hackathon Hackverse 2.0.

## Demo

The vendor's phone (PWA):
**https://outer-ensemble-pillow-three.trycloudflare.com/pwa/**

The IVR handset simulator is at `/` on the same host.

Open it on a phone, tap the green button, and speak. The mic needs a secure
context, which is the whole reason this is tunnelled rather than served over
the laptop's LAN address — `getUserMedia` does not exist on plain `http://`.

**That URL is temporary.** It is a cloudflared *quick tunnel*: it is bound to
one running `cloudflared` process and dies with it, so it changes every time
the backend is restarted. If the link above is dead, regenerate it:

```bash
.venv/bin/uvicorn services.api.main:app --host 0.0.0.0 --port 8000   # terminal 1
cloudflared tunnel --url http://localhost:8000                       # terminal 2
```

`cloudflared` prints the new `https://<something>.trycloudflare.com` on
startup. Update this section when it changes, or the link here is worse than
no link at all.

Give the API about a minute after it starts before timing anything: it warms
Whisper and a 2.4GB vision model in the background, and requests made during
that window measure several times slower than the same request afterwards.

## Languages

Eight: Hindi, English, Marathi, Gujarati, Bengali, Tamil, Telugu, Kannada.
`GET /api/ivr/languages` is the authoritative list and reports, per language,
whether its prompts can already be spoken offline.

Every one of them has been run end to end — speech in, spoken answer out — and
the real ASR transcripts are checked in as tests, in
`services/api/tests/test_profile.py`. Whisper answers Gujarati, Bengali and
Telugu *in Devanagari*, phonetically, so judge a language by whether age and
income survive rather than by how close the transcript looks to the original.

Telugu and Kannada run on Whisper `medium` (`voice.ASR_MODEL_FOR`); on `small`
they return unrelated tokens in unrelated scripts. Kannada takes about 88
seconds, which is slow but correct — pre-cache it if you plan to demo it.

You do not pick a language before speaking. Whisper detects it from the audio and
the whole reply follows — voice, text and the scheme cards. The language chips are
a fallback for when detection is unsure (`voice.DETECT_FLOOR`), not a prerequisite.

**Two things must be pre-cached before a demo, or the wifi-off run degrades:**

```bash
# 1. Spoken prompts. An uncached line is SILENT offline.
.venv/bin/python -c "import sys; sys.path[:0]=['.','services/api']; \
from channels import ivr_sim; print(ivr_sim.precache_prompts())"

# 2. Scheme-card text. Uncached, cards fall back to English rather than making
#    the caller wait — the serving path never calls the model.
.venv/bin/python -c "import sys; sys.path[:0]=['.','services/api']; \
from core import narrate; from channels import ivr_sim; \
print(narrate.precache_ui(ivr_sim.SUPPORTED_LANGUAGES))"
```

**After editing a prompt string, re-cache it:**

```bash
.venv/bin/python -c "import sys; sys.path[:0]=['.','services/api']; \
from channels import ivr_sim; print(ivr_sim.precache_prompts())"
```

edge-tts synthesises over the network, so an uncached line is *silent* with the
wifi off. `test_ivr_languages.py` fails until you do this, on purpose.

## Before you commit

Three tracked files change just from running the app, and none of those changes
belong in a commit:

```bash
git checkout -- services/api/data/chroma/ services/api/data/setu.db
```

`chroma/*` is rewritten merely by **reading** the index, and `setu.db` grows a
row every time a query is logged — which is correct behaviour, and still noise
in a diff. Committed cache files under `voice_cache/`, `narration_cache/` and
`profile_cache/` are the opposite: those are deliberate, and they are what lets
the demo run with the wifi off.
