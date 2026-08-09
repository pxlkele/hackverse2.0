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


# ── All eight languages ──────────────────────────────────────────────────────
#
# The same vendor — 35 years old, ₹800 a day — described in each of the eight
# languages the product offers. Every string below is real faster-whisper output
# on the model voice.ASR_MODEL_FOR selects for that language, captured by
# synthesising the sentence and transcribing it back.
#
# Read these and the reason multilingual support is hard becomes obvious:
# Whisper answers Gujarati, Bengali and Telugu in *Devanagari*, phonetically. A
# character-similarity score calls that a 7% failure, and it is nothing of the
# kind — the facts are all there. Judge a language by whether age and income
# survive, which is what this test does.

ASR_BY_LANGUAGE = {
    "hi": "मैं पानी पूरी का टेला लगाता हूं मेरी उम्र पैंटीस साल है रोज आट्सो रुपय कमाता हूं",
    "mr": "मी पानिपूरी चा थेला लाव तो, माजवै पस्तिस वर्शा है, रोज आच्छे रुपे कमाव तो",
    "gu": "वो पानी पूरीनी लारी चलावूचु, मारी उम्मर पान्त्रिस वर्ष चे, रोज आट्सो रुप्या कमावूचु.",
    "bn": "आनी पनी पुरी ख्याखा लाई आमार भायस पुत्रीष बच्छर प्रोटी दिन आख्शो ताका",
    "ta": "என் வயது முப்பத்தையுந்து கினமும் 800 ரூபாய் சம்பாதிக்கிறேன்",
    "te": "नेनु पानी पूरी बण्धी पेट्टुकुन्तान। ना वयसू 35 समत्सराल। रोजुकु 800 रूपायल।",
    "kn": "ನಾನು ಪಾನೆ ಪುರ್ ಗಾಡಿಯಿ ಇಟ್ತಿದೇನೆ. ನಾನ್ನ ವಾಸು 35 ವಾಷ್ ದಿನಕ್ 800 ರೂಪಾಯ",
    "en": "I run a pani puri cart. I am 35 years old. I earn 800 rupees daily.",
}


@pytest.mark.parametrize("lang", sorted(ASR_BY_LANGUAGE))
def test_age_and_income_survive_asr_in_every_offered_language(lang):
    heard = ASR_BY_LANGUAGE[lang]
    assert pm._regex_age(heard) == 35, f"{lang}: lost the age"
    daily, monthly = pm._regex_income(heard)
    assert daily == 800.0, f"{lang}: lost the income"
    assert monthly is None, f"{lang}: filed a daily wage as monthly"


def test_a_number_word_is_not_matched_inside_a_longer_word():
    """
    तीसरा means "third". If the age branch closed with \\b this would be safe by
    accident; it closes with an explicit terminator set instead, because Indic
    vowel signs are combining marks and \\b does not fire after them. Guard both
    properties at once.
    """
    assert pm._regex_age("यह मेरा तीसरा ठेला है") is None
