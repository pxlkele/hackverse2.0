"""
The answer and the card must be in the same language — the one that was spoken.

Two bugs sat behind this. A caller who spoke Marathi into a screen still set to
Hindi got a Hindi answer, because the language came from a chip they had to find
before speaking rather than from the speech itself. And the scheme cards stayed
English in every language, because the ladder text lives in schemes.yaml and only
the narration was ever translated — so the two halves of one reply disagreed.

No LLM is used here. Translation is cached to disk and the serving path is
cache-only by design, which is exactly what these tests pin down: a card must
never be able to make a caller wait.
"""

from __future__ import annotations

import pytest

from channels import ivr_sim
from services.api.core import eligibility, narrate, pathfinder, voice
from services.api.core.schemas import Profile


def vendor(**overrides) -> Profile:
    base = dict(
        occupation="pani puri vendor", occupation_category="street_vendor",
        sells_food=True, age=35, daily_income=800, monthly_income=20800,
        city="Bangalore", state="Karnataka", documents=[],
    )
    return Profile(**{**base, **overrides})


def decisions_for(profile: Profile):
    return pathfinder.build_all(profile, eligibility.evaluate_all(profile))


# ── Language detection ───────────────────────────────────────────────────────

def test_the_detection_floor_rejects_the_guesses_we_measured_as_wrong():
    """
    Measured probabilities on synthesised speech: mr .99, ta .99, te .98, hi .97,
    kn .95, bn .68 — and English misheard as Hindi at .36, Gujarati at .44. The
    floor has to sit above the two weak ones, because losing to the caller's own
    selection is the safer error.
    """
    assert 0.44 < voice.DETECT_FLOOR <= 0.68


def test_detection_only_ever_picks_a_language_we_support():
    assert set(ivr_sim.SUPPORTED_LANGUAGES) <= voice.ASR_LANGUAGES


# ── Card translation ────────────────────────────────────────────────────────

def test_card_strings_come_from_the_catalogue_not_from_one_ladder():
    """
    Which rungs appear depends on which documents the caller lacks. A pre-cache
    built from one well-documented vendor missed the Aadhaar rung, so the
    least-documented caller — the one who needs it most — got an English card.
    """
    strings = narrate.card_strings()
    assert strings
    assert any("Aadhaar" in s for s in strings)
    # The rung the whole demo turns on.
    assert any("Letter of Recommendation" in s for s in strings)


def test_english_is_never_translated():
    assert narrate.translate_ui("Open a Jan Dhan account", "en") == "Open a Jan Dhan account"


def test_the_serving_path_never_calls_the_model():
    """
    Fifteen card strings at a few seconds each would add a minute to the answer.
    An English card is much better than a slow one, so an uncached string on the
    serving path falls back rather than blocking.
    """
    never_seen = "A string that has certainly never been translated 8f3a1c"
    assert narrate.translate_ui(never_seen, "mr", allow_llm=False) == never_seen


# Both guards below use strings that are deliberately NOT in the catalogue, so
# they cannot be served from the pre-cache before the guard gets a chance to run.

def test_a_translation_that_drops_the_scheme_name_is_rejected(monkeypatch):
    """
    PM SVANidhi, FSSAI, PMSBY and PMJJBY stay in Latin on purpose: that is the
    name on the form and in the clerk's system. A caller cannot ask for a name
    that was translated away, so losing it fails the translation outright.

    Aadhaar and Jan Dhan are deliberately NOT guarded this way — they have
    standard native spellings, and demanding Latin for them rejected good
    translations and left most of the ladder in English.
    """
    monkeypatch.setattr(narrate, "chat", lambda **kw: "एक सरकारी योजना घ्या")
    original = "Apply for PM SVANidhi at the counter marked 9f2b71"
    assert narrate.translate_ui(original, "mr") == original


def test_runaway_output_is_rejected(monkeypatch):
    """Usually an explanation instead of a translation."""
    monkeypatch.setattr(narrate, "chat", lambda **kw: "explanation " * 200)
    original = "Open a savings account at window 4c8e20"
    assert narrate.translate_ui(original, "mr") == original


# ── The shape the phone renders ─────────────────────────────────────────────

@pytest.mark.parametrize("lang", ivr_sim.SUPPORTED_LANGUAGES)
def test_localise_decisions_always_gives_the_card_something_to_show(lang):
    """
    Every *_local field must be non-empty even with a cold cache, because the PWA
    renders `action_local || action` and a blank step is worse than an English one.
    """
    for card in narrate.localise_decisions(decisions_for(vendor()), lang):
        assert card["scheme_name_local"]
        for rung in card.get("ladder") or []:
            assert rung["action_local"]


def test_localising_leaves_the_audited_values_untouched():
    """A display translation has no business in the record of what was decided."""
    decisions = decisions_for(vendor())
    cards = narrate.localise_decisions(decisions, "mr")
    for decision, card in zip(decisions, cards):
        assert card["scheme_id"] == decision.scheme_id
        assert card["benefit_amount_rupees"] == decision.benefit_amount_rupees
        assert card["status"] == decision.status.value
        for rung, raw in zip(decision.ladder or [], card.get("ladder") or []):
            assert raw["action"] == rung.action          # original preserved
            assert raw["cost_rupees"] == rung.cost_rupees
