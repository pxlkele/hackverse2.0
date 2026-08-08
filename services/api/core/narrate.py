"""
Decision -> spoken vernacular.

The LLM's only job in the whole pipeline: turn a decision the rule engine
already made into a sentence a person can act on, in their language. It is
given the facts and told to phrase them. It is never asked what the answer is.

Everything numeric is interpolated by us, not generated, so the model cannot
invent a rupee figure or a deadline.
"""

from __future__ import annotations

from .llm import chat
from .schemas import Decision, EligibilityStatus, Profile

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


def narrate_all(profile: Profile, decisions: list[Decision], lang: str = "hi") -> str:
    """
    The whole answer, spoken. Leads with what he qualifies for today, then the
    nearest path — good news first, because the point is that he leaves with
    something actionable.
    """
    eligible = [d for d in decisions if d.status is EligibilityStatus.ELIGIBLE]
    laddered = [d for d in decisions if d.ladder]

    parts = []
    if eligible:
        # One short phrase per scheme, not the full benefit text - this is heard.
        for d in eligible:
            short = d.benefit_summary.split(".")[0].split("—")[0].strip()
            parts.append(f"You qualify today for {d.scheme_name}: {short}.")

    if laddered:
        best = min(laddered, key=lambda d: (d.total_cost_rupees or 0, d.total_time_days or 0))
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

    if not parts:
        parts.append("We could not find a matching scheme yet. Tell us a little more about your work.")

    language = LANG_NAMES.get(lang, "Hindi")
    text = chat(
        prompt=f"Say this in {language}:\n\n" + "\n".join(parts),
        system=SYSTEM,
        temperature=0.2,
    )
    return " ".join(text.split())


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
            "label": "Documents he has",
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
                "steps": [s.model_dump() for s in decision.ladder],
            })

    return steps
