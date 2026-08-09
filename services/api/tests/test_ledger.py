"""
Tests for the Voice Ledger.

The statement is the artifact a lender might act on, so the tests are mostly
about honesty: gaps must be reported rather than filled, provenance must be
stated rather than implied, and a suspiciously flat record must be flagged
rather than passed off as a clean one.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from services.api.core import ledger


@pytest.fixture()
def user(tmp_path, monkeypatch):
    """A ledger in a throwaway database, so tests never touch the demo data."""
    import sqlite3

    db = tmp_path / "ledger.db"

    def conn():
        c = sqlite3.connect(db)
        c.row_factory = sqlite3.Row
        return c

    monkeypatch.setattr(ledger, "get_conn", conn)
    ledger._ensure_table()
    return "test_vendor"


def speak(user, day_offset: int, earned: float, spent: float | None = None, *, end=None):
    """Write an entry directly, skipping the model."""
    on = (end or date.today()) - timedelta(days=day_offset)
    with ledger.get_conn() as c:
        c.execute(
            """INSERT INTO ledger_entries
               (user_id, on_date, earned, spent, source, corroborated, created_at)
               VALUES (?,?,?,?,'voice',0,'')
               ON CONFLICT(user_id, on_date, source) DO UPDATE SET
                 earned=excluded.earned, spent=excluded.spent""",
            (user, on.isoformat(), earned, spent),
        )
    return on


# ── the statement tells the truth about itself ───────────────────────────────

def test_coverage_is_reported_not_hidden(user):
    for i in range(10):
        speak(user, i, 800, 200)

    s = ledger.build_statement(user, days=30)
    assert s.days_covered == 10
    assert s.days_in_period == 30
    assert 0.33 == pytest.approx(s.coverage_pct, abs=0.01)
    assert any("10 of 30" in c for c in s.caveats)


def test_missing_days_are_never_estimated(user):
    """
    A statement that quietly interpolates absent days is a fabrication. Totals
    must reflect only what was actually said.
    """
    speak(user, 0, 1000, 100)
    speak(user, 5, 1000, 100)

    s = ledger.build_statement(user, days=30)
    assert s.total_earned == 2000, "absent days must not be filled in"
    assert s.days_covered == 2
    assert len(s.daily) == 2


def test_provenance_is_always_stated(user):
    speak(user, 0, 800)
    s = ledger.build_statement(user, days=30)
    assert "self-reported" in s.provenance


def test_empty_ledger_says_so_rather_than_showing_zeros(user):
    s = ledger.build_statement(user, days=30)
    assert s.days_covered == 0
    assert s.confidence == "indicative"
    assert any("No entries" in c for c in s.caveats)


# ── confidence reflects the evidence ─────────────────────────────────────────

def test_sparse_record_is_only_indicative(user):
    for i in range(5):
        speak(user, i, 800)
    s = ledger.build_statement(user, days=30)
    assert s.confidence == "indicative"
    assert any("not a basis for a lending decision" in c for c in s.caveats)


def test_uncorroborated_record_is_reasonable_at_best(user):
    for i in range(20):
        speak(user, i, 700 + i * 13)
    s = ledger.build_statement(user, days=30)
    assert s.confidence == "reasonable"
    assert s.corroboration_pct == 0.0
    assert any("nothing here is independently corroborated" in c for c in s.caveats)


def test_upi_corroboration_raises_confidence(user):
    end = date.today()
    days = [speak(user, i, 800, end=end) for i in range(20)]
    matched = ledger.add_upi_records(user, [(d, 800) for d in days[:15]])

    assert matched == 15
    s = ledger.build_statement(user, days=30, as_of=end)
    assert s.corroboration_pct >= 0.5
    assert s.confidence == "strong"


def test_upi_that_disagrees_does_not_corroborate(user):
    """A settlement far from the spoken figure is evidence of nothing."""
    end = date.today()
    days = [speak(user, i, 800, end=end) for i in range(10)]
    matched = ledger.add_upi_records(user, [(d, 3000) for d in days])
    assert matched == 0


# ── the smoothness flag ──────────────────────────────────────────────────────

def test_implausibly_flat_takings_are_flagged(user):
    """Real street-vending income is noisy. A flat line deserves a question."""
    for i in range(20):
        speak(user, i, 800)
    s = ledger.build_statement(user, days=30)
    assert any("unusually flat" in c for c in s.caveats)


def test_normal_variation_is_not_flagged(user):
    for i, amount in enumerate([620, 940, 810, 1180, 300, 760, 880, 1020,
                                690, 1310, 540, 900, 780, 1150]):
        speak(user, i, amount)
    s = ledger.build_statement(user, days=30)
    assert not any("unusually flat" in c for c in s.caveats)


# ── aggregates ───────────────────────────────────────────────────────────────

def test_totals_and_spread(user):
    for i, amount in enumerate([500, 1000, 750]):
        speak(user, i, amount, 100)

    s = ledger.build_statement(user, days=30)
    assert s.total_earned == 2250
    assert s.total_spent == 300
    assert s.net == 1950
    assert s.median_daily_earned == 750
    assert (s.best_day, s.worst_day) == (1000, 500)


def test_rendered_statement_leads_with_provenance(user):
    for i in range(20):
        speak(user, i, 700 + i * 11, 200)

    text = ledger.render_text(ledger.build_statement(user, days=30))
    assert text.index("SOURCE OF FIGURES") < text.index("SUMMARY"), (
        "a lender must see what this is before they see the totals"
    )
    assert "not a verified account" in text
    assert "Days covered" in text


# ── parsing spoken entries ───────────────────────────────────────────────────

def test_spoken_amounts_are_parsed_without_the_model():
    """
    The regex layer must stand alone: the model drops spoken Indian numerals
    unpredictably, and a dropped figure silently corrupts a month of record.
    """
    from services.api.core.profile import _SPOKEN_AMOUNT, _parse_amount

    amounts = [
        a for m in _SPOKEN_AMOUNT.finditer("aaj aath sau ka kaam hua, do sau ka maal liya")
        if (a := _parse_amount(m))
    ]
    assert amounts[:2] == [800.0, 200.0]
