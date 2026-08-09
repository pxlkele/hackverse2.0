# Setu — Making Invisible People Underwritable

Setu is a voice-first AI assistant that walks informal-sector workers from
their current situation to government schemes they qualify for.

Built for IBM Hackathon Hackverse 2.0.

## Demo

[Coming soon]

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
