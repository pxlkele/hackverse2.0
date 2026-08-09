"""
Tests for the deterministic layer of profile extraction.

No LLM is involved. Everything here is the regex safety net that runs *after*
Granite, and it exists because Granite drops numbers unpredictably — age and
income are the two fields that decide eligibility outright, so they must not
depend on a small model's mood.

Why this file is worth having:

The regex layer was originally written in romanised Hinglish ("saal", "sau",
"rupaye") while Whisper transcribes spoken Hindi in Devanagari. The entire net
therefore did nothing for voice input — the only input the product actually
takes — and the bug was invisible because testing was done by typing. It was
fixed by adding Devanagari, then found *again* on the canonical demo sentence,
because Whisper's Hindi is phonetic and misspells it in ways the first fix had
never seen.

So the cases below are not hypothetical strings. Each transcript marked "as
Whisper hears it" is real ASR output, captured by feeding synthesised speech
back through faster-whisper. That is the only kind of test that would have
caught either round of this bug.
"""

from __future__ import annotations

import pytest

from services.api.core import profile as pm

# The sentence the demo is built around, in three forms: as written, as Whisper
# actually transcribed it, and with Devanagari numerals.
DEMO_SPOKEN = (
    "मैं पानी पूरी का ठेला लगाता हूँ। मेरी उम्र पैंतीस साल है। "
    "रोज़ आठ सौ रुपये कमाता हूँ। मुझे काम बढ़ाने के लिए पैसे चाहिए।"
)
DEMO_HEARD = (
    "मैं पानी पूरी का टेला लगाता हूं मेरी उम्र पैंटीस साल है "
    "रोज आट्सो रुपय कमाता हूं मुझे काम बड़ाने के लिए पैसे चाहिए"
)


# ── Age ──────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "text",
    [
        "मैं 35 साल का हू",                      # bare digits, Whisper's clipped हू
        "मेरी उम्र पैंतीस साल है",                # number as a word, correctly spelled
        "मेरी उम्र पैंटीस साल है",                # ...and as Whisper misspells it
        "मेरी उम्र ३५ साल है",                    # Devanagari numerals
        "main 35 saal ka hoon",                  # romanised, for typed input
        DEMO_SPOKEN,
        DEMO_HEARD,
    ],
)
def test_age_35_survives_every_spelling(text):
    assert pm._regex_age(text) == 35


def test_years_in_business_is_not_read_as_an_age():
    """'saat saal se' is seven years of trading, not a seven-year-old vendor."""
    assert pm._regex_age("सात साल से यह काम कर रहा हूँ") is None


@pytest.mark.parametrize("text", ["मेरी उम्र दो साल है", "I am 130 years old"])
def test_impossible_ages_are_rejected(text):
    assert pm._regex_age(text) is None


# ── Income ───────────────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "text",
    [
        "रोज 8 सो रुपै कमाता हू",                 # Whisper's spelling of सौ and रुपये
        "रोज़ आठ सौ रुपये कमाता हूँ",              # correct
        "रोज आट्सो रुपय कमाता हूं",               # number fused onto its scale word
        "रोज़ ८०० रुपये कमाता हूँ",                # Devanagari numerals
        "roz aath sau rupaye kamata hoon",       # romanised
        DEMO_SPOKEN,
        DEMO_HEARD,
    ],
)
def test_daily_income_800_survives_every_spelling(text):
    daily, monthly = pm._regex_income(text)
    assert daily == 800.0
    assert monthly is None


def test_monthly_context_is_not_filed_as_daily():
    daily, monthly = pm._regex_income("महीने में बीस हज़ार कमाता हूँ")
    assert daily is None
    assert monthly == 20000.0


def test_an_amount_with_no_time_context_is_not_guessed():
    """Better a NEED_INFO than an invented income."""
    assert pm._regex_income("आठ सौ रुपये") == (None, None)


# ── Normalisation ────────────────────────────────────────────────────────────

def test_normalise_repairs_what_whisper_writes():
    fixed = pm._normalise(DEMO_HEARD)
    assert "आठ सौ" in fixed      # was fused as आट्सो
    assert "पैंतीस" in fixed      # was पैंटीस
    assert "ठेला" in fixed        # was टेला


def test_normalise_leaves_correct_spelling_alone():
    """The रुपये lookahead must not turn a correct word into रुपयेे."""
    assert pm._normalise(DEMO_SPOKEN) == DEMO_SPOKEN.translate(pm._DEV_DIGITS)


def test_occupation_category_and_food_come_from_the_heard_text():
    """These two drive PM SVANidhi and FSSAI, and are keyword-inferred."""
    assert "street_vendor" in str(pm.CATEGORY_WORDS.keys())
    assert any(word in DEMO_HEARD for word in pm.FOOD_WORDS)
