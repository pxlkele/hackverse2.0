"""
Speech (or typed text) -> structured Profile.

This is the only place the LLM touches the user's situation. It extracts; it
does not judge. Anything it can't find stays None, and a None field becomes a
NEED_INFO from the rule engine rather than a guess.

Design note: the prompt stays SHORT. granite4:tiny-h degrades badly on long
instruction lists — a earlier version with detailed rules for city/state,
occupation category and food detection made it *drop* fields it had previously
got right. Everything deterministic now happens in Python below, which is both
more reliable and cheaper to debug.
"""

from __future__ import annotations

import re
from typing import Any

from .llm import chat_json
from .schemas import Profile

SYSTEM = """Extract facts from how an Indian informal worker describes their life. Input may be Hindi, Hinglish or English.

Extract only what was said. Use null for anything not mentioned — never guess.

Numbers: sau=100, hazaar=1000, lakh=100000. ek1 do2 teen3 chaar4 paanch5 chhe6 saat7 aath8 nau9 das10.
"aath sau"=800. "saat saal se"=7 years in business.

has_existing_loan: true ONLY if they currently hold a loan ("loan liya hai", "EMI bharta hoon").
"loan chahiye" means they WANT one -> false, and it belongs in stated_need.

documents: only what they say they HAVE. If they say "nahi hai", leave it out."""

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "name": {"type": ["string", "null"]},
        "age": {"type": ["integer", "null"]},
        "gender": {"type": ["string", "null"], "enum": ["male", "female", "other", None]},
        "occupation": {"type": ["string", "null"]},
        "years_in_business": {"type": ["number", "null"]},
        "daily_income": {"type": ["number", "null"]},
        "monthly_income": {"type": ["number", "null"]},
        "city": {"type": ["string", "null"]},
        "state": {"type": ["string", "null"]},
        "documents": {
            "type": "array",
            "items": {
                "type": "string",
                "enum": [
                    "aadhaar", "pan", "voter_id", "ration_card", "bank_account",
                    "vending_certificate", "udyam", "fssai", "e_shram", "upi_qr",
                ],
            },
        },
        "has_existing_loan": {"type": ["boolean", "null"]},
        "stated_need": {"type": ["string", "null"]},
    },
    "required": ["occupation", "documents"],
}

CITY_TO_STATE = {
    "bangalore": "Karnataka", "bengaluru": "Karnataka", "mysore": "Karnataka",
    "mumbai": "Maharashtra", "pune": "Maharashtra", "nagpur": "Maharashtra",
    "delhi": "Delhi", "new delhi": "Delhi",
    "chennai": "Tamil Nadu", "coimbatore": "Tamil Nadu",
    "hyderabad": "Telangana", "kolkata": "West Bengal",
    "ahmedabad": "Gujarat", "surat": "Gujarat",
    "jaipur": "Rajasthan", "lucknow": "Uttar Pradesh", "kanpur": "Uttar Pradesh",
    "patna": "Bihar", "bhopal": "Madhya Pradesh", "indore": "Madhya Pradesh",
}

FOOD_WORDS = (
    "pani puri", "panipuri", "golgappa", "chaat", "samosa", "vada", "dosa",
    "idli", "tea", "chai", "juice", "fruit", "vegetable", "sabzi", "food",
    "snack", "momo", "roll", "bhel", "tiffin", "meal", "sweet", "ice cream",
)

CATEGORY_WORDS = {
    "street_vendor": ("thela", "cart", "hawker", "footpath", "roadside", "stall", "vendor", "rehri"),
    "artisan": ("tailor", "carpenter", "potter", "weaver", "cobbler", "blacksmith",
                "darzi", "artisan", "craft", "embroider"),
    "farmer": ("farmer", "kheti", "farm", "kisan", "agricultur"),
    "service": ("driver", "mechanic", "barber", "electrician", "plumber", "painter"),
    "trader": ("shop", "dukaan", "store", "trader", "retail"),
}

WANTS_LOAN = re.compile(
    r"loan\s+(chahiye|chaahiye|lena|leni|milega|mil sakta)|need\s+(a\s+)?loan|want\s+(a\s+)?loan",
    re.IGNORECASE,
)

# Spoken Indian numerals. The small model drops these unpredictably, so we
# parse them ourselves — a regex is deterministic and this is the field most
# likely to change an eligibility outcome.
_UNITS = {
    "ek": 1, "do": 2, "teen": 3, "char": 4, "chaar": 4, "paanch": 5, "panch": 5,
    "chhe": 6, "che": 6, "saat": 7, "aath": 8, "ath": 8, "nau": 9, "das": 10,
    "gyarah": 11, "barah": 12, "pandrah": 15, "bees": 20, "pachees": 25, "tees": 30,
}
_SCALES = {"sau": 100, "hazaar": 1000, "hazar": 1000, "lakh": 100000, "lac": 100000}

_NUM_WORDS = "|".join(sorted(_UNITS, key=len, reverse=True))
_SCALE_WORDS = "|".join(sorted(_SCALES, key=len, reverse=True))

# "aath sau", "do hazaar", "dhai hazaar", "800", "1500 rupaye"
_SPOKEN_AMOUNT = re.compile(
    rf"\b(?:(\d+)|({_NUM_WORDS}))\s*({_SCALE_WORDS})\b|\b(\d{{3,7}})\s*(?:rupaye|rupees|rs|ka)\b",
    re.IGNORECASE,
)
_DAILY_CONTEXT = re.compile(r"\b(roz|roj|daily|per day|din\s*ka|har din)\b", re.IGNORECASE)
_MONTHLY_CONTEXT = re.compile(r"\b(mahine|month|monthly|maheena)\b", re.IGNORECASE)

# Age vs. years-in-business both use "saal", so the surrounding words decide:
#   "34 saal ka hoon"  -> age 34        (ka/ki hoon, umar, age)
#   "saat saal se"     -> in business 7 (se = since)
_AGE = re.compile(
    rf"\b(?:umar|umra|age)\s*(?:hai|is)?\s*(\d{{1,3}})\b"
    rf"|\b(?:(\d{{1,3}})|({_NUM_WORDS}))\s*(?:saal|varsh|years?)\s*(?:ka|ki|kaa|kii)\s*(?:hoon|hun|hu|h)\b"
    rf"|\b(\d{{1,3}})\s*years?\s*old\b",
    re.IGNORECASE,
)

# "saat saal se", "7 saal se kaam", "2 years in business"
_YEARS_IN_BUSINESS = re.compile(
    rf"\b(?:(\d+(?:\.\d+)?)|({_NUM_WORDS}))\s*(?:saal|varsh|years?)\s*"
    rf"(?:se|from|of\s+(?:business|experience)|in\s+(?:this\s+)?(?:business|work|line))\b",
    re.IGNORECASE,
)


def _parse_amount(match: re.Match) -> float | None:
    digit, word, scale, bare = match.groups()
    if bare:
        return float(bare)
    if scale:
        base = float(digit) if digit else float(_UNITS.get((word or "").lower(), 0))
        return base * _SCALES[scale.lower()] if base else None
    return None


def _regex_income(text: str) -> tuple[float | None, float | None]:
    """(daily, monthly) — whichever the sentence context indicates."""
    for match in _SPOKEN_AMOUNT.finditer(text):
        amount = _parse_amount(match)
        if not amount:
            continue
        window = text[max(0, match.start() - 40) : match.end() + 40]
        if _DAILY_CONTEXT.search(window):
            return amount, None
        if _MONTHLY_CONTEXT.search(window):
            return None, amount
    return None, None


def _regex_years(text: str) -> float | None:
    """Years in business. Requires 'se'/'from' so it can't swallow an age."""
    match = _YEARS_IN_BUSINESS.search(text)
    if not match:
        return None
    digit, word = match.group(1), match.group(2)
    return float(digit) if digit else float(_UNITS.get((word or "").lower(), 0)) or None


def _regex_age(text: str) -> int | None:
    match = _AGE.search(text)
    if not match:
        return None
    for group in match.groups():
        if not group:
            continue
        value = int(group) if group.isdigit() else _UNITS.get(group.lower(), 0)
        if 10 <= value <= 110:  # anything outside this isn't an age
            return value
    return None

FIELDS_FOR_ELIGIBILITY = (
    "age", "occupation_category", "daily_income", "monthly_income",
    "state", "documents", "years_in_business",
)


def _enrich(data: dict[str, Any], text: str) -> tuple[dict[str, Any], list[str]]:
    """Deterministic post-processing. Cheaper and far more reliable than prompting."""
    derived: list[str] = []
    low = f"{text} {data.get('occupation') or ''}".lower()

    # Numbers first — the model drops these unpredictably and they drive eligibility.
    if not data.get("daily_income") and not data.get("monthly_income"):
        daily, monthly = _regex_income(text)
        if daily:
            data["daily_income"] = daily
            derived.append("daily_income parsed from text")
        if monthly:
            data["monthly_income"] = monthly
            derived.append("monthly_income parsed from text")

    if not data.get("years_in_business"):
        years = _regex_years(text)
        if years:
            data["years_in_business"] = years
            derived.append("years_in_business parsed from text")

    if not data.get("age"):
        age = _regex_age(text)
        if age:
            data["age"] = age
            derived.append("age parsed from text")

    # City, if the model missed it but we can see it in the text.
    if not data.get("city"):
        for city in CITY_TO_STATE:
            if re.search(rf"\b{re.escape(city)}\b", low):
                data["city"] = city.title()
                derived.append("city parsed from text")
                break

    # City -> state. The model reliably hears the city; the mapping is a lookup.
    if not data.get("state") and data.get("city"):
        state = CITY_TO_STATE.get(str(data["city"]).strip().lower())
        if state:
            data["state"] = state
            derived.append(f"state from city ({data['city']})")

    # Food vending, from the words they actually used.
    if any(word in low for word in FOOD_WORDS):
        data["sells_food"] = True
        derived.append("sells_food from occupation keywords")

    # Occupation category. Food sellers with no other signal are street vendors.
    if not data.get("occupation_category"):
        for category, words in CATEGORY_WORDS.items():
            if any(word in low for word in words):
                data["occupation_category"] = category
                derived.append(f"occupation_category from keywords ({category})")
                break
        else:
            if data.get("sells_food"):
                data["occupation_category"] = "street_vendor"
                derived.append("occupation_category inferred from food vending")

    # Guard the field most likely to wrongly disqualify someone: wanting a loan
    # is not having one, and small models conflate the two.
    if data.get("has_existing_loan") and WANTS_LOAN.search(text):
        data["has_existing_loan"] = False
        derived.append("has_existing_loan corrected: user wants a loan, does not hold one")

    # Monthly from daily. 26 working days is the conventional assumption for
    # daily-wage work, recorded as derived so the trace stays honest.
    if data.get("daily_income") and not data.get("monthly_income"):
        data["monthly_income"] = round(float(data["daily_income"]) * 26)
        derived.append("monthly_income from daily_income x 26")

    return data, derived


def extract(text: str, language: str = "hi") -> Profile:
    """Turn a free-form description into a Profile. Never raises on missing fields."""
    data = chat_json(
        prompt=f"Extract the facts:\n\n{text}",
        schema=SCHEMA,
        system=SYSTEM,
    )
    data, derived = _enrich(data, text)

    return Profile(
        raw_text=text,
        language=language,
        derived_fields=derived,
        **{k: v for k, v in data.items() if k in Profile.model_fields},
    )


def missing_for_eligibility(profile: Profile) -> list[str]:
    """Which facts we'd need before any scheme can be decided rather than deferred."""
    return [
        field
        for field in FIELDS_FOR_ELIGIBILITY
        if getattr(profile, field, None) in (None, [], "")
    ]
