"""
Tests for the Document Doctor.

Name comparison is pure and deterministic, so these run without any model. The
cases are drawn from how Indian identity documents actually differ: honorifics
on one card, initials on a passbook, transliteration variants of the same
spoken name.
"""

from __future__ import annotations

from services.api.core.doc_doctor import (
    ExtractedDoc,
    check,
    compare_names,
    normalise_name,
)


# ── normalisation ────────────────────────────────────────────────────────────

def test_titles_and_punctuation_are_stripped():
    assert normalise_name("Shri Ramesh Kumar") == "RAMESH KUMAR"
    assert normalise_name("RAMESH  KUMAR.") == "RAMESH KUMAR"
    assert normalise_name("Smt. Sunita Devi") == "SUNITA DEVI"


def test_relational_prefixes_are_stripped():
    """Passbooks often print S/O/W/O in the same field as the name."""
    assert normalise_name("Ramesh Kumar S/O Mohan Lal") == "RAMESH KUMAR MOHAN LAL"


# ── the case the whole feature exists for ────────────────────────────────────

def test_transliteration_variant_is_caught_as_a_spelling_difference():
    verdict, _ratio, why = compare_names("RAMESH KUMAR", "RAMESH KUMAAR")
    assert verdict == "spelling"
    assert "KUMAR vs KUMAAR" in why


def test_common_indic_vowel_variants():
    for a, b in [
        ("SUNITA DEVI", "SUNEETA DEVI"),
        ("GEETA SHARMA", "GITA SHARMA"),
        ("MUKESH YADAV", "MUKHESH YADAV"),
    ]:
        assert compare_names(a, b)[0] == "spelling", f"{a} vs {b}"


# ── things that are NOT problems ─────────────────────────────────────────────

def test_case_and_honorific_differences_are_not_flagged():
    assert compare_names("RAMESH KUMAR", "Ramesh Kumar")[0] == "match"
    assert compare_names("RAMESH KUMAR", "SHRI RAMESH KUMAR")[0] == "match"


# ── abbreviation vs misspelling: different problems, different fixes ─────────

def test_abbreviated_first_name():
    verdict, _r, why = compare_names("RAMESH KUMAR", "R KUMAR")
    assert verdict == "initial"
    assert "RAMESH vs R" in why


def test_abbreviated_middle_name():
    assert compare_names("RAMESH KUMAR SHARMA", "RAMESH K SHARMA")[0] == "initial"


def test_reordered_name():
    assert compare_names("RAMESH KUMAR", "KUMAR RAMESH")[0] == "reordered"


def test_genuinely_different_people():
    assert compare_names("RAMESH KUMAR", "SURESH PATEL")[0] == "mismatch"


def test_unreadable_name_is_not_silently_a_match():
    assert compare_names("", "RAMESH KUMAR")[0] == "mismatch"


# ── findings ─────────────────────────────────────────────────────────────────

def aadhaar(name: str, dob: str | None = None) -> ExtractedDoc:
    return ExtractedDoc(doc_type="aadhaar", name=name, dob=dob)


def passbook(name: str, dob: str | None = None) -> ExtractedDoc:
    return ExtractedDoc(doc_type="bank_passbook", name=name, dob=dob)


def test_matching_documents_produce_no_findings():
    assert check([aadhaar("RAMESH KUMAR"), passbook("Ramesh Kumar")]) == []


def test_mismatch_is_a_blocker_and_says_what_it_costs():
    findings = check([aadhaar("RAMESH KUMAR"), passbook("RAMESH KUMAAR")])
    assert len(findings) == 1

    finding = findings[0]
    assert finding.severity == "blocker"
    assert "Aadhaar card" in finding.message and "bank passbook" in finding.message
    assert finding.consequence, "a finding must say what it would have cost"
    assert finding.fix, "a finding must say how to fix it"


def test_conflicting_dates_of_birth_are_flagged():
    findings = check([
        aadhaar("RAMESH KUMAR", "01/01/1990"),
        passbook("RAMESH KUMAR", "12/06/1991"),
    ])
    assert any(f.field_name == "dob" and f.severity == "blocker" for f in findings)


def test_single_document_cannot_be_cross_checked():
    assert check([aadhaar("RAMESH KUMAR")]) == []


def test_unreadable_document_warns_rather_than_passing_silently():
    findings = check([aadhaar("RAMESH KUMAR"), passbook(None)])
    assert len(findings) == 1
    assert findings[0].severity == "warning"
    assert "retake" in findings[0].fix.lower()


def test_three_documents_are_compared_pairwise():
    findings = check([
        aadhaar("RAMESH KUMAR"),
        passbook("RAMESH KUMAAR"),
        ExtractedDoc(doc_type="voter_id", name="RAMESH KUMAR"),
    ])
    assert len(findings) == 2  # passbook vs each of the other two
