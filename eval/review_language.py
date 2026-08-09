"""
Play one language's prompts aloud, in call order, for a native speaker to judge.

    .venv/bin/python eval/review_language.py kn

The eight languages are verified mechanically — speech in, correct rupee figures
out — and not by anyone who speaks them. What machines cannot check is whether a
grammatical sentence is the sentence a person would actually say on a phone.

Ask, for each line:
  1. Would you say it this way OUT LOUD? Formal written phrasing is the usual
     failure. This is a phone call, not a form.
  2. Are the keypad numbers right — "press one", "press hash"?
  3. Is it too long? A listener cannot scroll back.
  4. Do PM SVANidhi / FSSAI / PMSBY sound right left in English? They are Latin
     on purpose: that is the name a bank clerk will recognise.
  5. Does the VOICE pronounce it correctly? Separate question from the text.

Run it as a file, not piped into python: it waits on your keyboard between lines.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path[:0] = [str(Path(__file__).resolve().parent.parent)]
sys.path[:0] = [str(Path(__file__).resolve().parent.parent / "services" / "api")]

from channels import ivr_sim  # noqa: E402
from services.api.core import voice  # noqa: E402

# Call order, which is what the reviewer should be judging — not just the
# individual sentences but whether the flow makes sense end to end.
ORDER = [
    ("ask_situation", "the main question — they answer this out loud"),
    ("thinking", "while the rules are checked"),
    ("after_answer", "the menu after an answer — keypad digits matter"),
    ("case_opened", "confirmation an application was started"),
    ("operator", "handing off to a human"),
    ("not_understood", "speech came back unusable"),
    ("nothing_heard", "nothing came back at all"),
]


def main() -> int:
    lang = (sys.argv[1] if len(sys.argv) > 1 else "").strip().lower()
    if lang not in ivr_sim.SUPPORTED_LANGUAGES:
        print("Usage: .venv/bin/python eval/review_language.py <code>")
        print("Codes:")
        for code in ivr_sim.SUPPORTED_LANGUAGES:
            print(f"   {code}   {ivr_sim.LANGUAGE_LABELS[code]}")
        return 1

    label = ivr_sim.LANGUAGE_LABELS[lang]
    print(f"\n{'=' * 66}")
    print(f"  {label}  ({lang}) — {len(ORDER)} lines")
    print(f"{'=' * 66}")
    print("  Enter plays the line. Type anything before Enter to note a problem.")
    print("  Ctrl-C to stop.\n")

    notes: list[tuple[str, str]] = []
    for key, what in ORDER:
        text = ivr_sim.PROMPTS[key].get(lang)
        if not text:
            continue
        print(f"\n[{key}] — {what}")
        print(f"  {text}")
        try:
            input("  Enter to play… ")
        except (EOFError, KeyboardInterrupt):
            print("\n  stopped")
            break
        try:
            voice.play(voice.speak(text, lang))
        except voice.VoiceError as exc:
            print(f"  (no audio: {exc})")
        try:
            note = input("  OK? Enter if fine, or type the fix: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n  stopped")
            break
        if note:
            notes.append((key, note))

    print(f"\n{'=' * 66}")
    if not notes:
        print(f"  {label}: no changes noted.")
    else:
        print(f"  {label}: {len(notes)} change(s). Paste this to Claude:\n")
        for key, note in notes:
            print(f"    {lang} / {key}: {note}")
    print(f"{'=' * 66}\n")
    print("  After editing PROMPTS in channels/ivr_sim.py, re-cache or the new")
    print("  wording is SILENT with the wifi off:")
    print("    .venv/bin/python -c \"import sys; sys.path[:0]=['.','services/api']; \\")
    print("      from channels import ivr_sim; print(ivr_sim.precache_prompts())\"")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
