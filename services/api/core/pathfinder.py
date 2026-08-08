"""
The Eligibility Path Engine — the ladder.

Every other scheme tool returns a verdict. This turns NOT_ELIGIBLE into a route:
the cheapest, fastest set of steps that flips a person to ELIGIBLE.

This is only possible because eligibility is typed rules rather than a model's
opinion. You can invert a rule; you cannot invert a vibe.

The search is deliberately simple. Rules are independent, so the minimal set of
mutations is just "fix every failing rule that has a remedy" — no combinatorial
search needed. What matters is ordering (cheap and fast first, so the user gets
an achievable next action) and honesty (if a failing rule has no remedy, say so
rather than pretending a path exists).
"""

from __future__ import annotations

import copy
from typing import Any

from .eligibility import evaluate_scheme, get_rule, get_scheme
from .schemas import Decision, EligibilityStatus, LadderStep, Profile

# What a remedy actually changes about the person's situation. Used both to
# order the ladder and to verify it works.
GRANTS_DOCUMENT_OPS = {"contains", "contains_any"}


def _remedy_grants(rule: dict[str, Any]) -> tuple[str, Any] | None:
    """
    What completing this remedy changes on the profile.

    Only document-shaped rules are auto-appliable today: finishing the remedy
    means you now hold the document. Income or age rules can't be "fixed" by an
    action, which is why they carry no remedy in schemes.yaml.
    """
    if rule["field"] != "documents" or rule["op"] not in GRANTS_DOCUMENT_OPS:
        return None
    value = rule.get("value")
    # contains_any: the remedy names which one it gets you; take the first.
    return ("documents", value[0] if isinstance(value, list) else value)


def apply_remedy(profile: Profile, rule: dict[str, Any]) -> Profile:
    """Return a copy of the profile as it would be after completing this remedy."""
    grant = _remedy_grants(rule)
    if not grant:
        return profile

    updated = copy.deepcopy(profile)
    field, value = grant
    if field == "documents" and value not in updated.documents:
        updated.documents = [*updated.documents, value]
    return updated


def build_ladder(profile: Profile, decision: Decision) -> Decision:
    """
    Attach a ladder to a NOT_ELIGIBLE decision.

    Returns the decision unchanged when it's already eligible, or when no failing
    rule has a remedy — a dead end must look like a dead end.
    """
    if decision.status != EligibilityStatus.NOT_ELIGIBLE:
        return decision

    scheme = get_scheme(decision.scheme_id)
    if not scheme:
        return decision

    steps: list[LadderStep] = []
    blocked_by: list[str] = []

    for result in decision.rules:
        if result.passed is not False:
            continue

        rule = get_rule(decision.scheme_id, result.rule_id)
        remedy = (rule or {}).get("remedy")

        if not remedy:
            blocked_by.append(result.description)
            continue

        steps.append(
            LadderStep(
                order=0,  # assigned after sorting
                action=remedy["action"],
                unblocks_rule=result.rule_id,
                cost_rupees=float(remedy.get("cost_rupees", 0)),
                time_days=int(remedy.get("time_days", 0)),
                where=remedy.get("where", ""),
                detail=" ".join(str(remedy.get("detail", "")).split()),
            )
        )

    # An unfixable rule means there is no honest path. Say nothing rather than
    # sending someone on a week of errands that can't work.
    if blocked_by or not steps:
        decision.ladder = None
        return decision

    # Cheapest first, then fastest — the user should be able to start today.
    steps.sort(key=lambda s: (s.cost_rupees, s.time_days))
    for i, step in enumerate(steps, 1):
        step.order = i

    decision.ladder = steps
    decision.total_cost_rupees = sum(s.cost_rupees for s in steps)
    # Steps are largely parallelisable, so the honest estimate is the longest
    # single step, not the sum.
    decision.total_time_days = max(s.time_days for s in steps)
    return decision


def verify_ladder(profile: Profile, decision: Decision) -> bool:
    """
    Does following this ladder actually make the person eligible?

    The property test that keeps the centrepiece honest. A ladder that doesn't
    lead anywhere is worse than no ladder — it costs a real person real days.
    """
    if not decision.ladder:
        return False

    scheme = get_scheme(decision.scheme_id)
    if not scheme:
        return False

    updated = profile
    for step in decision.ladder:
        rule = get_rule(decision.scheme_id, step.unblocks_rule)
        if rule:
            updated = apply_remedy(updated, rule)

    after = evaluate_scheme(updated, scheme)
    return after.status in (EligibilityStatus.ELIGIBLE, EligibilityStatus.NEED_INFO)


def build_all(profile: Profile, decisions: list[Decision]) -> list[Decision]:
    return [build_ladder(profile, d) for d in decisions]
