"""
Warm every cache the demo reads from, before the demo.

Granite runs at about 10 tokens per second on this laptop's CPU, so a narration
the cache has never seen costs 25-35 seconds while a vendor stands there. The
answer text is cached by content, and — this is the part that makes precaching
work at all — the facts it is built from come from the *scheme*, not from the
caller: rupee amounts, step counts, costs and days are all read off schemes.yaml.
Two vendors with different incomes who qualify for the same schemes produce a
byte-identical narration. So the set of distinct answers is small and finite,
and eval/personas.yaml already enumerates the situations we care about.

Run it before going on stage. It is idempotent — a second run costs nothing —
so run it again after any change to schemes.yaml, the ladder, or SYSTEM.

    .venv/bin/python eval/precache_narrations.py            # all 8 languages
    .venv/bin/python eval/precache_narrations.py hi mr kn   # just these
    .venv/bin/python eval/precache_narrations.py --dry-run  # count, pay nothing

--dry-run reports what is missing without calling the model, which is the only
honest way to answer "is the demo warm?" five minutes before you present.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "services" / "api"))

import yaml

from services.api.core import eligibility, narrate, pathfinder, voice
from services.api.core.schemas import Profile

from channels.ivr_sim import SUPPORTED_LANGUAGES  # noqa: E402  the one list of languages

PERSONAS = Path(__file__).resolve().parent / "personas.yaml"


def load_personas() -> list[dict]:
    with open(PERSONAS) as fh:
        return yaml.safe_load(fh)["personas"]


def answers_for(personas: list[dict]) -> list[tuple[str, list]]:
    """
    Every persona's decisions, computed once. No LLM here: eligibility and the
    ladder are pure rules, so this is the cheap half and it runs in a second.
    """
    out = []
    for persona in personas:
        profile = Profile(**persona["profile"])
        decisions = pathfinder.build_all(profile, eligibility.evaluate_all(profile))
        out.append((persona["id"], profile, decisions))
    return out


def main(argv: list[str]) -> int:
    dry_run = "--dry-run" in argv
    langs = [a for a in argv if not a.startswith("-")] or list(SUPPORTED_LANGUAGES)
    unknown = [l for l in langs if l not in SUPPORTED_LANGUAGES]
    if unknown:
        print(f"unknown language(s): {unknown}. Known: {list(SUPPORTED_LANGUAGES)}")
        return 2

    personas = load_personas()
    rows = answers_for(personas)
    print(f"{len(personas)} personas x {len(langs)} languages = {len(rows) * len(langs)} turns")
    print(f"languages: {' '.join(langs)}\n")

    if dry_run:
        cached = len(list(narrate.CACHE_DIR.glob("*.txt"))) if narrate.CACHE_DIR.exists() else 0
        spoken = len(list(voice.CACHE_DIR.glob("*.mp3"))) if voice.CACHE_DIR.exists() else 0
        ui = len(list(narrate.UI_CACHE_DIR.glob("*"))) if narrate.UI_CACHE_DIR.exists() else 0
        print(f"narration cache: {cached} answers on disk")
        print(f"voice cache    : {spoken} mp3 files on disk")
        print(f"card strings   : {ui} on disk")
        print("\nRun without --dry-run to fill anything missing.")
        return 0

    started = time.monotonic()
    narrations: dict[str, str] = {}      # text -> lang, deduplicated across personas
    llm_calls = 0
    failures: list[tuple[str, str, str]] = []

    for lang in langs:
        hits = 0
        for persona_id, profile, decisions in rows:
            t0 = time.monotonic()
            try:
                text = narrate.narrate_all(profile, decisions, lang)
            except Exception as exc:  # noqa: BLE001
                # One bad turn must not cost the other 167. The first run of
                # this script died on the second Gujarati persona and left
                # gu/bn/ta/te/kn cold - the exact languages it existed to warm.
                failures.append((lang, persona_id, type(exc).__name__))
                print(f"  [{lang}] {persona_id:<22} FAILED {type(exc).__name__}", flush=True)
                continue
            took = time.monotonic() - t0
            if took > 3.0:               # anything that fast came from disk
                llm_calls += 1
                print(f"  [{lang}] {persona_id:<22} generated in {took:5.1f}s")
            else:
                hits += 1
            narrations[text] = lang
        print(f"  [{lang}] {hits}/{len(rows)} already cached")

    print(f"\nnarration: {len(narrations)} distinct answers, {llm_calls} needed the model")

    # Every distinct answer also needs its mp3, or the phone falls back to the
    # device voice mid-demo — which sounds nothing like the rest of the run.
    print("\nsynthesising audio for each distinct answer...")
    spoke, failed = 0, 0
    for text, lang in narrations.items():
        try:
            voice.speak(text, lang)
            spoke += 1
        except voice.VoiceError as exc:
            failed += 1
            print(f"  TTS failed [{lang}]: {str(exc)[:90]}")
    print(f"audio: {spoke} ready, {failed} failed")

    # The scheme cards on the phone are translated from a separate cache, and a
    # miss there is silent: the card just stays in English.
    print("\ncard strings...")
    translated = narrate.precache_ui(tuple(langs))
    print(f"cards: {translated} strings cached")

    print(f"\ndone in {time.monotonic() - started:.0f}s")
    if failures:
        print(f"\n{len(failures)} turn(s) did NOT cache - these still pay full price live:")
        for lang, persona_id, kind in failures:
            print(f"  [{lang}] {persona_id} ({kind})")
        print("Re-run to retry just those; everything else is already on disk.")
        return 1
    print("The demo path is now cache-only. Re-run after any schemes.yaml change.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
