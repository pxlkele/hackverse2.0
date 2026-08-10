"""
The eligibility engine.

Pure functions over typed rules. No LLM anywhere in this file, by design:
every decision must be deterministic, replayable, and explainable by pointing at
the government text it came from.

Three-valued on purpose:
    ELIGIBLE      every required rule passed
    NOT_ELIGIBLE  at least one required rule failed
    NEED_INFO     nothing failed, but we're missing facts needed to decide

A missing fact is never treated as a failure. Telling someone they don't qualify
because they didn't mention their age is exactly the behaviour this product
exists to replace.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from .schemas import Citation, Decision, EligibilityStatus, Profile, RuleResult

SCHEMES_PATH = Path(__file__).resolve().parent.parent / "data" / "schemes.yaml"

def _annual_turnover(p: Profile) -> float | None:
    """
    Annual turnover from whatever the person actually said.

    Most informal workers quote a daily figure, not a monthly one, so deriving
    only from monthly_income left turnover unknown for nearly everyone. 26
    working days is the conventional assumption for daily-wage work.
    """
    if p.monthly_income:
        return p.monthly_income * 12
    if p.daily_income:
        return p.daily_income * 26 * 12
    return None


# Fields a rule may reference that aren't stored directly on Profile.
DERIVED_FIELDS = {
    "annual_turnover": _annual_turnover,
    # Only an NPA/written-off loan disqualifies. Merely holding a loan does not,
    # and conflating the two would wrongly reject a large share of applicants.
    "has_existing_loan_npa": lambda p: None,
}


@lru_cache(maxsize=1)
def load_schemes() -> dict[str, Any]:
    with open(SCHEMES_PATH) as fh:
        return yaml.safe_load(fh)


def schemes_version() -> str:
    return str(load_schemes().get("version", "0"))


def _field_value(profile: Profile, field: str) -> Any:
    if field in DERIVED_FIELDS:
        return DERIVED_FIELDS[field](profile)
    return getattr(profile, field, None)


def _compare(actual: Any, op: str, expected: Any) -> bool | None:
    """Returns None when the comparison can't be made (missing fact)."""
    if actual is None:
        return None

    try:
        match op:
            case "eq":
                return actual == expected
            case "ne":
                return actual != expected
            case "gt":
                return float(actual) > float(expected)
            case "gte":
                return float(actual) >= float(expected)
            case "lt":
                return float(actual) < float(expected)
            case "lte":
                return float(actual) <= float(expected)
            case "in":
                return actual in expected
            case "not_in":
                return actual not in expected
            case "contains":
                return expected in (actual or [])
            case "contains_any":
                return bool(set(actual or []) & set(expected))
            case "not_contains":
                return expected not in (actual or [])
            case "is_true":
                return actual is True
            case "is_false":
                return actual is False
            case _:
                raise ValueError(f"unknown operator: {op}")
    except (TypeError, ValueError):
        return None


def _format(value: Any) -> str:
    if value is None:
        return "not stated"
    if isinstance(value, list):
        return ", ".join(str(v) for v in value) if value else "none"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _describe_expectation(rule: dict[str, Any]) -> str:
    op, value = rule["op"], rule.get("value")
    match op:
        case "contains":
            return f"must have {value}"
        case "contains_any":
            return "must have one of: " + ", ".join(value)
        case "eq":
            return f"must be {value}"
        case "lt":
            return f"must be under {_format(value)}"
        case "lte":
            return f"must be at most {_format(value)}"
        case "gt":
            return f"must be over {_format(value)}"
        case "gte":
            return f"must be at least {_format(value)}"
        case "is_true":
            return "must be true"
        case "is_false":
            return "must not apply"
        case _:
            return f"{op} {value}"


def evaluate_rule(profile: Profile, rule: dict[str, Any]) -> RuleResult:
    actual = _field_value(profile, rule["field"])
    passed = _compare(actual, rule["op"], rule.get("value"))

    citation = None
    if rule.get("source_quote") and not str(rule["source_quote"]).startswith("PENDING"):
        citation = Citation(
            source_doc=rule.get("source_doc", ""),
            page_no=int(rule.get("source_page", 0)),
            heading=rule.get("description", ""),
            snippet=" ".join(str(rule["source_quote"]).split()),
        )

    return RuleResult(
        rule_id=rule["id"],
        description=rule["description"],
        passed=passed,
        expected=_describe_expectation(rule),
        actual=_format(actual),
        citation=citation,
    )


def evaluate_scheme(profile: Profile, scheme: dict[str, Any]) -> Decision:
    results = [evaluate_rule(profile, rule) for rule in scheme["rules"]]

    by_id = {rule["id"]: rule for rule in scheme["rules"]}
    failed = [r for r in results if r.passed is False]

    # An optional rule we can't evaluate shouldn't hold up a decision.
    unknown = [
        r for r in results
        if r.passed is None and not by_id[r.rule_id].get("optional", False)
    ]

    # A gating rule says who the scheme is *for*. If we don't know that, no
    # other failure is worth reporting — telling someone to go get a vending
    # certificate is wasted advice if they turn out not to be a vendor.
    gating_unknown = [r for r in unknown if by_id[r.rule_id].get("gating", False)]

    if gating_unknown:
        status = EligibilityStatus.NEED_INFO
    elif failed:
        status = EligibilityStatus.NOT_ELIGIBLE
    elif unknown:
        status = EligibilityStatus.NEED_INFO
    else:
        status = EligibilityStatus.ELIGIBLE

    return Decision(
        scheme_id=scheme["id"],
        scheme_name=scheme["name"],
        status=status,
        rules=results,
        missing_fields=list(dict.fromkeys(by_id[r.rule_id]["field"] for r in unknown)),
        benefit_summary=" ".join(str(scheme.get("benefit_summary", "")).split()),
        benefit_amount_rupees=scheme.get("benefit_amount_rupees"),
    )


def evaluate_all(profile: Profile, include_draft: bool = False) -> list[Decision]:
    """Every live scheme, best outcomes first."""
    schemes = [
        s for s in load_schemes()["schemes"]
        if include_draft or s.get("status") != "draft"
    ]

    decisions = [evaluate_scheme(profile, s) for s in schemes]

    order = {
        EligibilityStatus.ELIGIBLE: 0,
        EligibilityStatus.NOT_ELIGIBLE: 1,  # ranked above NEED_INFO: a ladder beats a shrug
        EligibilityStatus.NEED_INFO: 2,
    }
    by_id = {s["id"]: s for s in schemes}
    decisions.sort(key=lambda d: (order[d.status], by_id[d.scheme_id].get("priority", 99)))
    return decisions


def get_scheme(scheme_id: str) -> dict[str, Any] | None:
    return next((s for s in load_schemes()["schemes"] if s["id"] == scheme_id), None)


def get_rule(scheme_id: str, rule_id: str) -> dict[str, Any] | None:
    scheme = get_scheme(scheme_id)
    if not scheme:
        return None
    return next((r for r in scheme["rules"] if r["id"] == rule_id), None)


# Attributes a fair-lending regime would flag if a rule referenced them.
# The audit checks that no rule field is one of these — the stronger fairness
# claim than "outcomes are balanced across groups" is "the engine cannot see
# these attributes at all."
PROTECTED_ATTRIBUTES = ("gender", "caste", "religion", "race", "ethnicity")


def rule_field_audit() -> dict[str, Any]:
    """
    How many rules exist, which fields they use, and how many touch a protected
    attribute. Fairness by construction, provable from schemes.yaml.
    """
    fields_used: dict[str, int] = {}
    total = 0
    protected_hits: list[str] = []

    for scheme in load_schemes()["schemes"]:
        for rule in scheme.get("rules", []):
            total += 1
            field = rule.get("field", "")
            fields_used[field] = fields_used.get(field, 0) + 1
            if field in PROTECTED_ATTRIBUTES:
                protected_hits.append(f"{scheme['id']}:{rule['id']}")

    return {
        "total_rules": total,
        "protected_attributes": list(PROTECTED_ATTRIBUTES),
        "protected_rule_count": len(protected_hits),
        "protected_rule_ids": protected_hits,
        "fields_used": fields_used,
    }
