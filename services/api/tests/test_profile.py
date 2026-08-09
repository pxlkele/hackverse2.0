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
    "ta": (
        "நான் பானி பூரி தள்ளு வண்டி வைத்திருக்கிறேன் என் வயது முப்பத்தையுந்து "
        "கினமும் 800 ரூபாய் சம்பாதிக்கிறேன்"
    ),
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


# ── False positives ─────────────────────────────────────────────────────────
#
# Everything above asks "did we catch the fact". These ask the harder question:
# did we catch something that was never there. A missed income shows up as a
# NEED_INFO the caller can correct; an invented one silently changes eligibility.

def test_employment_is_not_read_as_daily():
    """
    "रोजगार" is employment. "रोज" is daily. \\b cannot close a Devanagari word,
    so the daily-context pattern used to match inside रोजगार and file a *monthly*
    wage as a daily one — a 26x overstatement, checked against PM SVANidhi's
    income cap, which denies a vendor a scheme he qualifies for. MGNREGA is
    रोजगार गारंटी, so this is vocabulary the product will absolutely hear.
    """
    daily, monthly = pm._regex_income("मुझे रोजगार चाहिए। महीने में बीस हज़ार कमाता हूँ।")
    assert daily is None
    assert monthly == 20000.0


def test_a_phone_number_is_not_an_amount():
    """The bare-digits branch is bounded at both ends for this reason."""
    daily, _ = pm._regex_income("मेरा नंबर 9876543210 है, रोज़ आठ सौ कमाता हूँ")
    assert daily == 800.0


def test_english_income_without_the_word_rupees():
    """"20000 a month" names no currency and was read as no income at all."""
    daily, monthly = pm._regex_income("I earn 20000 a month")
    assert (daily, monthly) == (None, 20000.0)


@pytest.mark.parametrize(
    "text",
    [
        "I earn 2000 everyday",          # the phrasing that exposed this
        "I earn 2000 every day",
        "2000 everyday",
        "I make 2000 rupees everyday",
        "I earn 2000 daily",
        "I earn 2000 a day",
        "I earn 2000 each day",
        "roz 2000 kamata hoon",
        "rozana 2000",
        "रोज़ाना दो हज़ार",
        "हर रोज़ 2000",
        "रोज़ दो हज़ार रुपये कमाता हूँ",
        "मैं रोज़ 2000 कमाता हूँ",
    ],
)
def test_every_natural_phrasing_of_a_daily_wage(text):
    """
    "everyday" was missing from the daily-context list, so four of seven ways of
    saying the same sentence returned no income at all — including "I earn 2000
    rupees everyday", which names both the amount and the currency. A dropped
    income is not visibly wrong, it just quietly becomes a NEED_INFO.
    """
    daily, monthly = pm._regex_income(text)
    assert daily == 2000.0
    assert monthly is None


@pytest.mark.parametrize(
    "text,expected",
    [
        ("I earn 52000 a month", 52000.0),
        ("I earn 52000 per month", 52000.0),
        ("I earn 52000 monthly", 52000.0),
        ("महीने में बीस हज़ार", 20000.0),
        ("हर महीने 20000", 20000.0),
    ],
)
def test_monthly_phrasings(text, expected):
    daily, monthly = pm._regex_income(text)
    assert monthly == expected
    assert daily is None


def test_rent_is_not_income():
    """An amount with no daily or monthly word beside it is never assumed."""
    assert pm._regex_income("दुकान का किराया आठ सौ है") == (None, None)


def test_a_number_word_is_not_matched_inside_a_longer_word():
    """
    तीसरा means "third". If the age branch closed with \\b this would be safe by
    accident; it closes with an explicit terminator set instead, because Indic
    vowel signs are combining marks and \\b does not fire after them. Guard both
    properties at once.
    """
    assert pm._regex_age("यह मेरा तीसरा ठेला है") is None


# ── Real speech from the vendor's own phone ──────────────────────────────────
#
# Everything above was captured by synthesising a sentence and transcribing it
# back. These four are different: they are what faster-whisper returned from a
# person actually speaking into the PWA over a phone mic, read out of the
# server log. They are messier than the synthetic set, and they are the reason
# Marathi answered "I did not catch your age and your earnings" to every single
# thing that was said to it.

REAL_PHONE_SPEECH = {
    # "पाणी पुरीचं दुकान चालवतो" - I run a pani puri shop.
    "mr_pani_puri": ("भी पाने पूरी से दुगान चालमतो अनी मास्ता व्यवस्ताई वानोड़े", "mr"),
    # The ordinary Marathi spelling, which was simply absent from FOOD_WORDS -
    # so a Marathi speaker saying it *correctly* also extracted nothing.
    "mr_correct_spelling": ("मी पाणी पुरीचं दुकान चालवतो", "mr"),
    "mr_vada_pav": ("मी वडापाव विकतो", "mr"),
    "gu_pani_puri": ("पानी पूरी नी दुकान जला बूशु में मारा काम", "gu"),
}


@pytest.mark.parametrize("key", sorted(REAL_PHONE_SPEECH))
def test_real_phone_speech_yields_something_to_reason_from(key):
    """
    Not asserting a particular category: "trader" and "street_vendor" are both
    defensible readings of "I run a pani puri shop", and which one comes back
    depends on the model. What must never happen is nothing at all, because an
    empty profile is what makes the channel re-prompt instead of answering.
    """
    text, lang = REAL_PHONE_SPEECH[key]
    profile = pm.extract(text, language=lang, use_cache=False)
    assert profile.sells_food is True
    assert profile.occupation_category is not None


def test_keyword_tables_are_in_the_cache_fingerprint():
    """
    Adding a spelling to FOOD_WORDS must invalidate cached profiles, or the
    caller who reported the bug keeps getting the answer their stale cache
    entry holds. The number tables were covered from the start; the keyword
    tables were not, which made the fix invisible to exactly the person it was
    written for.
    """
    before = pm._rules_fingerprint()
    original = pm.FOOD_WORDS
    try:
        pm.FOOD_WORDS = original + ("a-spelling-that-did-not-exist",)
        assert pm._rules_fingerprint() != before
    finally:
        pm.FOOD_WORDS = original
    assert pm._rules_fingerprint() == before
