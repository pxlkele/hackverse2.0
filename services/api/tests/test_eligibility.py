"""
Tests for the eligibility engine and the ladder.

These encode actual government rules, so they are the correctness backbone of
the whole product. If one of these fails, a real person gets wrong advice.

No LLM is involved — profiles are constructed directly, so these run in
milliseconds and are safe to run on every save.
"""

from __future__ import annotations

import pytest

from services.api.core import eligibility as el
from services.api.core import pathfinder as pf
from services.api.core.schemas import EligibilityStatus, Profile

SVANIDHI = "pm_svanidhi"


def vendor(**overrides) -> Profile:
    """A street vendor who qualifies for everything, unless told otherwise."""
    base = dict(
        occupation="pani puri vendor",
        occupation_category="street_vendor",
        sells_food=True,
        daily_income=800,
        monthly_income=20800,
        years_in_business=7,
        city="Bangalore",
        state="Karnataka",
        documents=["aadhaar", "bank_account", "upi_id", "vending_certificate"],
    )
    return Profile(**{**base, **overrides})


def decide(profile: Profile):
    scheme = el.get_scheme(SVANIDHI)
    return el.evaluate_scheme(profile, scheme)


# ── Core outcomes ────────────────────────────────────────────────────────────

def test_fully_documented_vendor_is_eligible():
    assert decide(vendor()).status is EligibilityStatus.ELIGIBLE


def test_letter_of_recommendation_is_accepted_instead_of_certificate():
    """Category C vendors use an LoR — the scheme treats it as equivalent."""
    profile = vendor(documents=["aadhaar", "bank_account", "upi_id", "letter_of_recommendation"])
    assert decide(profile).status is EligibilityStatus.ELIGIBLE


def test_missing_vending_proof_is_not_eligible():
    profile = vendor(documents=["aadhaar", "bank_account", "upi_id"])
    assert decide(profile).status is EligibilityStatus.NOT_ELIGIBLE


def test_non_vendor_is_not_eligible():
    profile = vendor(occupation_category="artisan")
    assert decide(profile).status is EligibilityStatus.NOT_ELIGIBLE


# ── The rule that matters most: never guess ──────────────────────────────────

def test_unknown_occupation_asks_rather_than_rejects():
    """
    The whole point of the product. Someone who didn't mention their occupation
    must not be told they don't qualify.
    """
    profile = vendor(occupation_category=None)
    decision = decide(profile)
    assert decision.status is EligibilityStatus.NEED_INFO
    assert "occupation_category" in decision.missing_fields


def test_optional_rule_does_not_block_when_unknown():
    """NPA status is usually unknown; it must not stall an otherwise clean match."""
    decision = decide(vendor())
    npa = next(r for r in decision.rules if r.rule_id == "svanidhi_no_npa")
    assert npa.passed is None
    assert decision.status is EligibilityStatus.ELIGIBLE


def test_wanting_a_loan_is_not_holding_one():
    """Regression: the model once set has_existing_loan=True for 'loan chahiye'."""
    profile = vendor(has_existing_loan=True)
    assert decide(profile).status is EligibilityStatus.ELIGIBLE


# ── Citations ────────────────────────────────────────────────────────────────

def test_every_live_rule_cites_a_real_document():
    for scheme in el.load_schemes()["schemes"]:
        if scheme.get("status") == "draft":
            continue
        for rule in scheme["rules"]:
            assert rule.get("source_doc"), f"{rule['id']} has no source document"
            assert rule.get("source_quote"), f"{rule['id']} has no source quote"
            assert not str(rule["source_quote"]).startswith("PENDING")


def test_failing_rule_carries_its_citation():
    decision = decide(vendor(documents=["aadhaar", "bank_account", "upi_id"]))
    failed = next(r for r in decision.rules if r.passed is False)
    assert failed.citation is not None
    assert failed.citation.source_doc
    assert failed.citation.page_no > 0


# ── The ladder ───────────────────────────────────────────────────────────────

def test_ladder_appears_for_missing_vending_proof():
    profile = vendor(documents=["aadhaar", "bank_account", "upi_id"])
    decision = pf.build_ladder(profile, decide(profile))

    assert decision.ladder, "a fixable failure must produce a ladder"
    assert len(decision.ladder) == 1
    assert decision.total_cost_rupees == 0
    assert decision.total_time_days == 7


def test_missing_upi_adds_a_rung():
    """UPI is required and easy to miss — it must appear as its own step."""
    profile = vendor(documents=["aadhaar", "bank_account", "vending_certificate"])
    decision = pf.build_ladder(profile, decide(profile))
    assert decision.ladder and len(decision.ladder) == 1
    assert decision.ladder[0].unblocks_rule == "svanidhi_upi_id"
    assert pf.verify_ladder(profile, decision) is True


def test_following_the_ladder_actually_makes_you_eligible():
    """
    The property test that keeps the centrepiece honest. A ladder that leads
    nowhere costs a real person real days.
    """
    profile = vendor(documents=["aadhaar", "bank_account", "upi_id"])
    decision = pf.build_ladder(profile, decide(profile))
    assert pf.verify_ladder(profile, decision) is True


def test_ladder_covers_multiple_missing_documents():
    profile = vendor(documents=[])
    decision = pf.build_ladder(profile, decide(profile))
    assert decision.ladder and len(decision.ladder) >= 3
    assert pf.verify_ladder(profile, decision) is True


def test_ladder_is_ordered_cheapest_and_fastest_first():
    profile = vendor(documents=[])
    decision = pf.build_ladder(profile, decide(profile))
    keys = [(s.cost_rupees, s.time_days) for s in decision.ladder]
    assert keys == sorted(keys)
    assert [s.order for s in decision.ladder] == list(range(1, len(keys) + 1))


def test_no_ladder_when_the_failure_cannot_be_remedied():
    """Being an artisan is not fixable; we must not invent a path."""
    profile = vendor(occupation_category="artisan")
    decision = pf.build_ladder(profile, decide(profile))
    assert decision.ladder is None


def test_eligible_decision_gets_no_ladder():
    decision = pf.build_ladder(vendor(), decide(vendor()))
    assert decision.ladder is None


# ── Determinism ──────────────────────────────────────────────────────────────

def test_same_profile_produces_identical_decisions():
    profile = vendor(documents=["aadhaar"])
    first = pf.build_all(profile, el.evaluate_all(profile))
    second = pf.build_all(profile, el.evaluate_all(profile))
    assert [d.model_dump() for d in first] == [d.model_dump() for d in second]


def test_draft_schemes_are_excluded_by_default():
    """
    Drafts must never reach a user — a scheme with PENDING citations would show
    an unverifiable claim in the Why? panel.
    """
    all_schemes = el.load_schemes()["schemes"]
    drafts = {s["id"] for s in all_schemes if s.get("status") == "draft"}

    live_ids = {d.scheme_id for d in el.evaluate_all(vendor())}
    assert live_ids.isdisjoint(drafts)

    every_id = {s["id"] for s in all_schemes}
    assert {d.scheme_id for d in el.evaluate_all(vendor(), include_draft=True)} == every_id


def test_food_vendor_matches_both_schemes():
    """The real demo path: one person, two schemes, one of them laddered."""
    profile = vendor(documents=["aadhaar", "bank_account", "upi_id"])
    decisions = pf.build_all(profile, el.evaluate_all(profile))
    by_id = {d.scheme_id: d for d in decisions}

    assert by_id["fssai_basic"].status is EligibilityStatus.ELIGIBLE
    assert by_id["pm_svanidhi"].status is EligibilityStatus.NOT_ELIGIBLE
    assert by_id["pm_svanidhi"].ladder


# ── Age vs. years-in-business ────────────────────────────────────────────────

def test_age_and_tenure_are_not_confused():
    """
    Both use "saal" in Hindi. "34 saal ka hoon" is an age; "saat saal se" is how
    long they've traded. Getting these backwards silently breaks PMSBY.
    """
    from services.api.core.profile import _regex_age, _regex_years

    text = "Main 34 saal ka hoon, saat saal se yeh kaam kar raha hoon."
    assert _regex_age(text) == 34
    assert _regex_years(text) == 7


def test_tenure_alone_is_not_read_as_an_age():
    from services.api.core.profile import _regex_age, _regex_years

    text = "Saat saal se pani puri ka thela chalata hoon."
    assert _regex_age(text) is None
    assert _regex_years(text) == 7


def test_missing_fields_are_deduplicated():
    """Two age rules must not report 'age' twice to the user."""
    profile = vendor(age=None)
    decision = el.evaluate_scheme(profile, el.get_scheme("pmsby"))
    assert decision.missing_fields == ["age"]


def test_pmsby_age_bounds():
    assert el.evaluate_scheme(vendor(age=34), el.get_scheme("pmsby")).status is EligibilityStatus.ELIGIBLE
    assert el.evaluate_scheme(vendor(age=17), el.get_scheme("pmsby")).status is EligibilityStatus.NOT_ELIGIBLE
    assert el.evaluate_scheme(vendor(age=75), el.get_scheme("pmsby")).status is EligibilityStatus.NOT_ELIGIBLE


def test_age_failure_offers_no_false_hope():
    """Nobody can act their way out of being 75. No ladder."""
    profile = vendor(age=75)
    decision = pf.build_ladder(profile, el.evaluate_scheme(profile, el.get_scheme("pmsby")))
    assert decision.ladder is None


def test_every_citation_is_verbatim_from_its_pdf():
    """
    The product's central claim is that any decision traces to a real line of a
    real government document. A paraphrased quote breaks that the moment a judge
    opens the PDF, so this runs as part of the ordinary test suite.

    Skipped when the source PDFs are not present (they are large; a clone that
    only wants the engine does not need them).
    """
    import subprocess
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parents[3]
    if not (root / "ingestion" / "sources").exists():
        pytest.skip("source PDFs not present")

    result = subprocess.run(
        [sys.executable, str(root / "eval" / "verify_citations.py")],
        capture_output=True, text=True, cwd=root,
    )
    assert result.returncode == 0, result.stdout
