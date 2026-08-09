"""
Decision -> spoken vernacular.

The LLM's only job in the whole pipeline: turn a decision the rule engine
already made into a sentence a person can act on, in their language. It is
given the facts and told to phrase them. It is never asked what the answer is.

Every number is interpolated by us, not generated. That is necessary and it is
not sufficient: the model still has to carry our numbers through translation,
and measured, it does not always — granite4:tiny-h turned ₹2,00,000 into
२०००००० when asked for Marathi. So the narration is checked against the facts
it was built from before it is spoken, and rejected if the money moved. See
_misstated_money.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from . import eligibility
from .llm import chat
from .profile import categories_in
from .schemas import Decision, EligibilityStatus, Profile

# Generating four schemes' worth of Hindi takes granite4:tiny-h ~25s, far too
# slow to do live. The decisions are deterministic, so the sentence is too:
# cache it by the content it was generated from. A rehearsed demo line is
# written once and read from disk forever after, which also means the demo
# speaks with the wifi off.
CACHE_DIR = Path(__file__).resolve().parent.parent / "data" / "narration_cache"


def _cache_key(parts: list[str], lang: str) -> str:
    payload = json.dumps({"parts": parts, "lang": lang}, sort_keys=True)
    return hashlib.sha1(payload.encode()).hexdigest()[:20]


# Indic digit scripts, so a number the model wrote as २०००००० or ௮௦௦ is compared
# on the same footing as one it wrote as 2000000.
_ANY_DIGITS = str.maketrans(
    "०१२३४५६७८९" "০১২৩৪৫৬৭৮৯" "૦૧૨૩૪૫૬૭૮૯" "௦௧௨௩௪௫௬௭௮௯" "౦౧౨౩౪౫౬౭౮౯" "೦೧೨೩೪೫೬೭೮೯",
    "0123456789" * 6,
)

# Below this we do not police the wording: step counts and day estimates get
# legitimately rephrased ("about two days"). At and above it, every number is
# money, and money is the one thing that must survive translation exactly.
_MONEY_FLOOR = 100


def _amounts_in(text: str) -> set[int]:
    return {
        int(run)
        for run in re.findall(r"\d+", text.translate(_ANY_DIGITS))
        if int(run) >= _MONEY_FLOOR
    }


def _misstated_money(spoken: str, parts: list[str]) -> set[int]:
    """
    Amounts the narration states that the facts never contained.

    This exists because the prompt below already says "Never change a number"
    and the model does it anyway. Measured: asked for Marathi, granite4:tiny-h
    rendered PMSBY's ₹2,00,000 as २०००००० — twenty lakh, a tenfold overstatement
    of a government benefit, twice in one answer. Telling a street vendor he is
    owed ₹20,00,000 is the single worst thing this product could say, so it is
    checked rather than requested.
    """
    return _amounts_in(spoken) - _amounts_in(" ".join(parts))


def _cached(key: str) -> str | None:
    path = CACHE_DIR / f"{key}.txt"
    return path.read_text() if path.exists() else None


def _store(key: str, text: str) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    (CACHE_DIR / f"{key}.txt").write_text(text)

SYSTEM = """You are speaking ALOUD to an Indian street vendor, directly, as "you".

Rewrite the facts into at most 4 short spoken sentences in the requested language.

Rules:
- Speak TO the person, never about them. Use "aap" / "you", never "he" or "usko".
- Say ONLY what the facts state. Never add a scheme, amount, document or deadline.
- Never change a number.
- This is heard, not read. No lists, no brackets, no markdown, no English jargon.
- Name schemes, but do not recite their full benefit text - one short phrase each.
- End with the single next action they should take.
- Warm and direct. No apologies, no "unfortunately"."""

LANG_NAMES = {
    "hi": "Hindi", "mr": "Marathi", "kn": "Kannada", "ta": "Tamil",
    "te": "Telugu", "bn": "Bengali", "gu": "Gujarati", "en": "simple English",
}

# IVR menu appended after every spoken response so the caller knows their options.
# Keyed by language code; falls back to English.
_IVR_MENU: dict[str, str] = {
    "hi": "Ek dabaayen dobara sunne ke liye. Do dabaayen avedan shuru karne ke liye. Shunya dabaayen kisi se baat karne ke liye.",
    "mr": "Parat aikanyasaathi ek daba. Arj suruu karnyasaathi don daba. Khunaashee bolanyasaathi shunya daba.",
    "kn": "Matte kelalu ondu odiri. Arzeji praarambhisalu eradu odiri. Yaavaadaru mathaadalu sonne odiri.",
    "ta": "Meendum ketka onrai azhuthu. Vinnappam thodannga irandai azhuthu. Yaraavadhu pesave poiyai azhuthu.",
    "te": "Meeru vinaalante okati napaandi. Darkhaastu prarambhinchadam kosam rendu napaandi. Evaritonaaina maatlaadadam kosam sunna napaandi.",
    "bn": "Abaar shunate ek chaapun. Abedon shuru korte dui chaapun. Karo sathe kotha bolte shunya chaapun.",
    "en": "Press one to hear this again. Press two to start your application. Press zero to speak with someone.",
}


def _facts(decision: Decision) -> str:
    lines = [f"Scheme: {decision.scheme_name}", f"Benefit: {decision.benefit_summary}"]

    if decision.status is EligibilityStatus.ELIGIBLE:
        lines.append("Result: You qualify right now and can apply today.")

    elif decision.status is EligibilityStatus.NEED_INFO:
        lines.append(
            "Result: We cannot decide yet. We need to know: "
            + ", ".join(decision.missing_fields)
        )

    elif decision.ladder:
        lines.append(
            f"Result: You do not qualify yet, but there is a path: "
            f"{len(decision.ladder)} steps, total cost {decision.total_cost_rupees:.0f} rupees, "
            f"about {decision.total_time_days} days."
        )
        for step in decision.ladder:
            cost = "free" if step.cost_rupees == 0 else f"{step.cost_rupees:.0f} rupees"
            lines.append(f"Step {step.order}: {step.action}. {cost}, {step.time_days} days. At: {step.where}")
    else:
        failed = [r.description for r in decision.rules if r.passed is False]
        lines.append("Result: You do not qualify, and this cannot be changed. Reason: " + "; ".join(failed))

    return "\n".join(lines)


def narrate_decision(decision: Decision, lang: str = "hi") -> str:
    """One decision, spoken."""
    language = LANG_NAMES.get(lang, "Hindi")
    text = chat(
        prompt=f"Say this in {language}:\n\n{_facts(decision)}",
        system=SYSTEM,
        temperature=0.2,
    )
    return " ".join(text.split())


def _needed_categories(profile: Profile) -> set[str]:
    """Which scheme categories the caller actually asked about."""
    return categories_in(f"{profile.stated_need or ''} {profile.raw_text or ''}")


def _category_of(decision: Decision) -> str | None:
    scheme = eligibility.get_scheme(decision.scheme_id)
    return (scheme or {}).get("category")


def rank_decisions(profile: Profile, decisions: list[Decision]) -> list[Decision]:
    """
    Speaking order, deliberately in this priority:

        1. what they actually asked for
        2. then cheapest to reach
        3. then the largest benefit

    Ranking on cost alone - which is what this did - answers a man asking for a
    loan by telling him about accident insurance, because insurance is cheaper
    to qualify for. On a phone call he only really hears the first thing, so
    the order is the answer.
    """
    wanted = _needed_categories(profile)
    return sorted(
        decisions,
        key=lambda d: (
            0 if _category_of(d) in wanted else 1,      # asked for it
            d.total_cost_rupees or 0,                   # cheapest
            -(d.benefit_amount_rupees or 0),            # biggest money
            d.total_time_days or 0,                     # tie-break: soonest
        ),
    )


UI_CACHE_DIR = Path(__file__).resolve().parent.parent / "data" / "ui_cache"

# Names that must never be translated. These are how the scheme is written on the
# form, on the bank's poster and in the clerk's system — a vendor who asks for a
# translated name gets a blank look. Latin here is not laziness, it is the thing
# that makes the advice usable.
# Only the scheme identifiers. These are brands: they appear on the form, the
# bank's poster and the clerk's screen exactly like this, and a caller who asks
# for a translated one gets a blank look.
#
# Aadhaar, Jan Dhan and UPI deliberately are NOT here. They have standard native
# spellings — आधार, जन धन — that every speaker recognises, and demanding Latin
# for them rejected perfectly good translations: that mistake left every rung
# mentioning Aadhaar or Jan Dhan in English, which is most of the ladder.
KEEP_VERBATIM = ("PM SVANidhi", "SVANidhi", "FSSAI", "PMSBY", "PMJJBY")

UI_SYSTEM = """Translate the phrase into the requested language.

Rules:
- Output ONLY the translation. No quotes, no notes, no alternatives.
- Keep every scheme name, document name and abbreviation EXACTLY as given, in
  Latin script: PM SVANidhi, FSSAI, PMSBY, PMJJBY, Aadhaar, Jan Dhan, UPI, LoR,
  CSC. These are what a bank clerk recognises.
- Keep every number and every rupee figure exactly as given.
- This is read off a phone screen by someone with low literacy: short, plain,
  spoken register. No formal or bureaucratic wording."""


def translate_ui(text: str, lang: str, allow_llm: bool = True) -> str:
    """
    Translate one short interface string, cached on disk forever.

    The ladder steps live in schemes.yaml in English, so the cards on the phone
    stayed English while the spoken answer was in the caller's language — the two
    halves of the same reply disagreeing with each other.

    Cached per (text, language) because these strings are a fixed, small set: four
    schemes' rungs, and they never change between runs. Pre-cache them with
    precache_ui() and this costs nothing at demo time. Uncached it costs an LLM
    call, so it must never be on the critical path unprepared.
    """
    if lang == "en" or not text or not text.strip():
        return text

    # A string that is *only* a scheme name has nothing to translate. Short-circuit
    # rather than spend an LLM call to be told so.
    if text.strip() in KEEP_VERBATIM or text.strip() in ("FSSAI Basic Registration",):
        return text

    key = hashlib.sha1(f"{lang}:{text}".encode()).hexdigest()[:20]
    path = UI_CACHE_DIR / f"{key}.txt"
    if path.exists():
        return path.read_text()

    # Serving a request: never pay for a translation now. Fifteen card strings at
    # a few seconds each would add over a minute to the answer, which is worse
    # than an English card by a wide margin. Return English and let precache_ui
    # fill this in before the demo.
    if not allow_llm:
        return text

    language = LANG_NAMES.get(lang, "Hindi")
    try:
        out = " ".join(
            chat(prompt=f"Into {language}:\n\n{text}", system=UI_SYSTEM, temperature=0.0).split()
        )
    except Exception:  # noqa: BLE001 - English on the card beats no card
        return text

    # A translation that dropped the scheme name is worse than no translation:
    # the caller cannot act on a name that is not there.
    for name in KEEP_VERBATIM:
        if name.lower() in text.lower() and name.lower() not in out.lower():
            return text
    if not out or len(out) > 4 * len(text) + 40:
        return text          # runaway output, almost always an explanation

    UI_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(out)
    return out


def localise_decisions(decisions: list[Decision], lang: str) -> list[dict]:
    """
    Decisions as dicts, with the caller-facing strings in their language.

    Returns plain dicts rather than Decision objects: the schemas are frozen by
    team agreement, and a display translation has no business in the audited
    record of what the rules decided.
    """
    out: list[dict] = []
    for decision in decisions:
        data = decision.model_dump(mode="json")
        # Cache-only: this runs while a caller is waiting.
        data["scheme_name_local"] = translate_ui(decision.scheme_name or "", lang, allow_llm=False)
        data["benefit_summary_local"] = translate_ui(
            decision.benefit_summary or "", lang, allow_llm=False
        )
        for rung, raw in zip(decision.ladder or [], data.get("ladder") or []):
            raw["action_local"] = translate_ui(rung.action or "", lang, allow_llm=False)
            raw["where_local"] = translate_ui(rung.where or "", lang, allow_llm=False)
        out.append(data)
    return out


def card_strings() -> list[str]:
    """
    Every string that can ever appear on a card, taken from schemes.yaml.

    Enumerating the catalogue rather than one profile's ladder, because which
    rungs appear depends on which documents the caller lacks. A pre-cache built
    from a single well-documented vendor missed the "Enrol for Aadhaar" rung
    entirely — so the one caller who needed it, the least-documented one, got an
    English card.
    """
    schemes = eligibility.load_schemes()
    found: list[str] = []
    for scheme in schemes.get("schemes", []):
        for key in ("name", "benefit_summary"):
            if scheme.get(key):
                found.append(str(scheme[key]))
        for rule in scheme.get("rules", []):
            remedy = rule.get("remedy") or {}
            for key in ("action", "where"):
                if remedy.get(key):
                    found.append(str(remedy[key]))
    return sorted(set(found))


def precache_ui(languages: tuple[str, ...] | list[str]) -> int:
    """Translate every card string into every language, once, before the demo."""
    done = 0
    for lang in languages:
        if lang == "en":
            continue
        for text in card_strings():
            translate_ui(text, lang)
            done += 1
    return done


def narrate_all(profile: Profile, decisions: list[Decision], lang: str = "hi") -> str:
    """
    The whole answer, spoken, in the order the caller cares about: what they
    asked for first, then cheapest, then biggest.
    """
    ranked = rank_decisions(profile, decisions)
    eligible = [d for d in ranked if d.status is EligibilityStatus.ELIGIBLE]
    laddered = [d for d in ranked if d.ladder]

    parts = []
    if eligible:
        # One short phrase per scheme, not the full benefit text - this is heard.
        for d in eligible:
            short = d.benefit_summary.split(".")[0].split("—")[0].strip()
            parts.append(f"You qualify today for {d.scheme_name}: {short}.")

    if laddered:
        best = laddered[0]
        amount = (
            f"up to {best.benefit_amount_rupees:.0f} rupees"
            if best.benefit_amount_rupees else "this scheme"
        )
        cost = "free" if not best.total_cost_rupees else f"{best.total_cost_rupees:.0f} rupees"
        parts.append(
            f"For {best.scheme_name} you can get {amount}. You are "
            f"{len(best.ladder)} steps away - {cost}, about {best.total_time_days} days."
        )
        parts.append(f"Your first step: {best.ladder[0].action}, at {best.ladder[0].where}.")

        # The rest get one line each. A caller cannot hold four ladders in their
        # head, but they should still hear that the other doors exist.
        for other in laddered[1:3]:
            other_amount = (
                f"up to {other.benefit_amount_rupees:.0f} rupees"
                if other.benefit_amount_rupees else "help"
            )
            parts.append(
                f"You can also get {other_amount} from {other.scheme_name}, "
                f"{len(other.ladder)} steps away."
            )

    if not parts:
        parts.append("We could not find a matching scheme yet. Tell us a little more about your work.")

    key = _cache_key(parts, lang)
    hit = _cached(key)
    # Checked on the way out of the cache as well as on the way in. These files
    # are committed, and several were written before this guard existed — one of
    # them holds the ₹20,00,000 Marathi line. A cache that can serve a figure the
    # live path would now reject is just a slower way to say the wrong thing.
    if hit and not _misstated_money(hit, parts):
        return _with_ivr_menu(hit, lang)

    language = LANG_NAMES.get(lang, "Hindi")
    prompt = f"Say this in {language}:\n\n" + "\n".join(parts)

    # Two attempts, then English. The retry drops to temperature 0 because the
    # failure we are recovering from is the model being creative with a rupee
    # figure. If both attempts misstate money we speak the facts in English
    # rather than a fluent lie: a vendor who hears the right number in the wrong
    # language can still act on it, and the operator console shows the text.
    text = ""
    for temperature in (0.2, 0.0):
        text = " ".join(chat(prompt=prompt, system=SYSTEM, temperature=temperature).split())
        if not _misstated_money(text, parts):
            _store(key, text)
            return _with_ivr_menu(text, lang)

    bad = _misstated_money(text, parts)
    print(
        f"narrate: refusing {lang} narration, invented amounts {sorted(bad)}; "
        f"falling back to English facts",
        flush=True,
    )
    fallback = " ".join(parts)
    _store(key, fallback)
    return _with_ivr_menu(fallback, lang)


def _with_ivr_menu(text: str, lang: str) -> str:
    """Append the IVR keypad menu so the caller actually hears their options."""
    menu = _IVR_MENU.get(lang, _IVR_MENU["en"])
    return f"{text} {menu}"


def reasoning_steps(profile: Profile, decisions: list[Decision]) -> list[dict]:
    """
    The visible thought process, as a flat list the UI can reveal one at a time.

    These are the real evaluations, not a re-enactment — each row is a rule that
    actually fired, with the document it came from.
    """
    steps: list[dict] = []

    heard = []
    if profile.occupation:
        heard.append(profile.occupation)
    if profile.city:
        heard.append(profile.city)
    if profile.daily_income:
        heard.append(f"₹{profile.daily_income:.0f}/day")
    if profile.age:
        heard.append(f"age {profile.age}")
    steps.append({"kind": "heard", "label": "Understood", "detail": " · ".join(heard)})

    if profile.documents:
        steps.append({
            "kind": "heard",
            "label": "Documents they have",
            "detail": ", ".join(profile.documents),
        })

    for decision in decisions:
        docs = {r.citation.source_doc for r in decision.rules if r.citation}
        steps.append({
            "kind": "scheme",
            "label": decision.scheme_name,
            "detail": f"{len(decision.rules)} rules · {len(docs)} government document(s)",
            "status": decision.status.value,
        })

        for rule in decision.rules:
            steps.append({
                "kind": "rule",
                "scheme": decision.scheme_name,
                "passed": rule.passed,
                "label": rule.description,
                "expected": rule.expected,
                "actual": rule.actual,
                "citation": (
                    f"{rule.citation.source_doc} p{rule.citation.page_no}"
                    if rule.citation else ""
                ),
                "quote": rule.citation.snippet if rule.citation else "",
            })

        if decision.ladder:
            steps.append({
                "kind": "ladder",
                "scheme": decision.scheme_name,
                "label": f"Found a path: {len(decision.ladder)} steps",
                "detail": f"₹{decision.total_cost_rupees:.0f} · {decision.total_time_days} days",
                "steps": [s.model_dump(mode="json") for s in decision.ladder],
            })

    return steps
