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
from .schemas import Citation, Decision, EligibilityStatus, LadderStep, Profile

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

        # A remedy may cite a different document from the rule it unblocks:
        # the Category C provision that makes a Letter of Recommendation valid
        # lives in the loan operations guidelines, not the scheme guidelines.
        quote = remedy.get("source_quote") or rule.get("source_quote")
        citation = None
        if quote and not str(quote).startswith("PENDING"):
            using_remedy_source = bool(remedy.get("source_quote"))
            citation = Citation(
                source_doc=(remedy.get("source_doc") if using_remedy_source else None)
                           or rule.get("source_doc", ""),
                page_no=int(
                    (remedy.get("source_page") if using_remedy_source else None)
                    or rule.get("source_page") or 0
                ),
                heading=remedy["action"],
                snippet=" ".join(str(quote).split()),
            )

        steps.append(
            LadderStep(
                order=0,  # assigned after sorting
                action=remedy["action"],
                unblocks_rule=result.rule_id,
                cost_rupees=float(remedy.get("cost_rupees", 0)),
                time_days=int(remedy.get("time_days", 0)),
                where=remedy.get("where", ""),
                detail=" ".join(str(remedy.get("detail", "")).split()),
                citation=citation,
            )
        )

    # An unfixable rule means there is no honest path. Say nothing rather than
    # sending someone on a week of errands that can't work.
    if blocked_by or not steps:
        decision.ladder = None
        return decision

    # Order by dependency first, then cheapest and fastest within what is
    # currently doable. Sorting purely by cost and time produced ladders nobody
    # could follow: "create a UPI ID linked to your bank account" as step 1 for
    # someone who has no bank account, and "enrol for Aadhaar" as step 4 when
    # the account in step 2 requires it.
    depends = {
        s.unblocks_rule: set(
            ((get_rule(decision.scheme_id, s.unblocks_rule) or {}).get("remedy") or {})
            .get("depends_on", [])
        )
        for s in steps
    }
    present = {s.unblocks_rule for s in steps}
    # A dependency already satisfied by the profile is not a blocker.
    depends = {k: (v & present) for k, v in depends.items()}

    # Among the steps someone could start today, do the one that unblocks the
    # longest remaining chain first. Aadhaar takes 30 days and gates the bank
    # account and the UPI ID; a Letter of Recommendation takes 7 and gates
    # nothing. Listing the LoR first because it is quicker would leave the long
    # pole untouched for a week.
    chain = _chain_lengths(steps, depends)

    ordered: list[LadderStep] = []
    done: set[str] = set()
    remaining = list(steps)

    while remaining:
        ready = [s for s in remaining if depends[s.unblocks_rule] <= done]
        if not ready:
            # A cycle in the data. Fall back rather than dropping steps, and let
            # the ladder-verification test surface it.
            ready = sorted(remaining, key=lambda s: (s.cost_rupees, s.time_days))[:1]
        nxt = min(
            ready,
            key=lambda s: (-chain[s.unblocks_rule], s.cost_rupees, s.time_days),
        )
        ordered.append(nxt)
        done.add(nxt.unblocks_rule)
        remaining.remove(nxt)

    for i, step in enumerate(ordered, 1):
        step.order = i

    decision.ladder = ordered
    decision.total_cost_rupees = sum(s.cost_rupees for s in ordered)
    decision.total_time_days = _critical_path_days(ordered, depends)
    return decision


def _chain_lengths(steps: list[LadderStep], depends: dict[str, set[str]]) -> dict[str, int]:
    """Days from starting each step until everything downstream of it is done."""
    by_rule = {s.unblocks_rule: s for s in steps}
    dependents: dict[str, list[str]] = {r: [] for r in by_rule}
    for rule, prerequisites in depends.items():
        for prerequisite in prerequisites:
            if prerequisite in dependents:
                dependents[prerequisite].append(rule)

    memo: dict[str, int] = {}

    def longest(rule: str, seen: frozenset[str] = frozenset()) -> int:
        if rule in memo:
            return memo[rule]
        if rule in seen:  # cycle guard
            return by_rule[rule].time_days
        downstream = [
            longest(child, seen | {rule}) for child in dependents.get(rule, [])
        ]
        memo[rule] = by_rule[rule].time_days + max(downstream, default=0)
        return memo[rule]

    return {rule: longest(rule) for rule in by_rule}


def _critical_path_days(steps: list[LadderStep], depends: dict[str, set[str]]) -> int:
    """
    How long the whole ladder really takes.

    Independent steps run in parallel, so the answer is not the sum. Dependent
    ones run in sequence, so it is not the maximum either — it is the longest
    chain. Telling someone "30 days" when Aadhaar must finish before the bank
    account can start understates it by two days, and the point of the number is
    that they can plan around it.
    """
    finish: dict[str, int] = {}
    for step in steps:
        prerequisites = depends.get(step.unblocks_rule, set())
        start = max((finish.get(p, 0) for p in prerequisites), default=0)
        finish[step.unblocks_rule] = start + step.time_days
    return max(finish.values(), default=0)


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
