"""
Voice Ledger — building a credit history out of spoken sentences.

Every evening the vendor says five seconds of Hindi: "aaj aath sau ka kaam hua,
do sau ka maal liya." Thirty of those become a cash-flow statement a loan
officer can actually read.

The point is not bookkeeping. A street vendor is not uncreditworthy — nobody
has ever counted what he earns. This counts it, and hands him the record.

Three commitments, because the alternative is a product that quietly launders
guesses into an official-looking document:

  Provenance is printed, not implied. The statement says it is self-reported,
  how many days it covers, and how much of it was corroborated. A lender is
  told exactly what they are holding.

  Gaps are reported, not hidden. Nobody speaks every night. A statement built
  from 22 of 30 days says so; that is more credible to a loan officer than a
  suspiciously complete record, and far more honest.

  Implausible smoothness is flagged. Real vendor income is noisy — rain,
  festivals, dead Mondays. Invented numbers come out flat, and we say so
  rather than pretending we can detect fraud we cannot.
"""

from __future__ import annotations

import json
import re
import sqlite3
import statistics
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

from .llm import chat_json
from .store import get_conn

# 30 days is the shortest window a lender will read as a pattern rather than
# an anecdote, and it is also what a vendor can plausibly sustain.
STATEMENT_DAYS = 30

# Below this, the record is too sparse to characterise a business. We still
# produce a statement, but it is labelled as indicative rather than a basis
# for a decision.
MIN_DAYS_FOR_CONFIDENCE = 14

ENTRY_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "earned": {"type": ["number", "null"]},
        "spent": {"type": ["number", "null"]},
        "note": {"type": ["string", "null"]},
    },
}

ENTRY_SYSTEM = """Extract today's takings from one spoken sentence by an Indian street vendor.

earned = money taken in today. spent = money paid out for stock or supplies today.
Use null for anything not said. Never guess, never carry a figure over from another day.

Numbers: sau=100, hazaar=1000. "aath sau"=800, "do sau"=200, "dhai hazaar"=2500.
"aaj aath sau ka kaam hua, do sau ka maal liya" -> earned 800, spent 200."""


@dataclass
class Entry:
    """One evening's spoken record."""

    on: date
    earned: float | None = None
    spent: float | None = None
    note: str = ""
    raw_text: str = ""
    source: str = "voice"          # voice | upi | manual
    corroborated: bool = False     # matched against a UPI record


@dataclass
class Statement:
    """What a lender receives."""

    user_id: str
    period_start: date
    period_end: date

    days_covered: int
    days_in_period: int
    coverage_pct: float

    total_earned: float
    total_spent: float
    net: float
    median_daily_earned: float
    best_day: float
    worst_day: float

    provenance: str
    corroboration_pct: float
    confidence: str                # indicative | reasonable | strong
    caveats: list[str] = field(default_factory=list)
    daily: list[dict[str, Any]] = field(default_factory=list)


# ── storage ──────────────────────────────────────────────────────────────────

def _ensure_table() -> None:
    with get_conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS ledger_entries (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id      TEXT NOT NULL,
                on_date      TEXT NOT NULL,
                earned       REAL,
                spent        REAL,
                note         TEXT,
                raw_text     TEXT,
                source       TEXT DEFAULT 'voice',
                corroborated INTEGER DEFAULT 0,
                created_at   TEXT,
                UNIQUE(user_id, on_date, source)
            );
        """)


def parse_entry(text: str) -> tuple[float | None, float | None, str]:
    """
    One spoken sentence -> (earned, spent, note).

    Numbers are parsed by the same regex layer the profile uses, because the
    model drops spoken Indian numerals unpredictably and a dropped figure here
    silently corrupts a month of record.
    """
    from .profile import _SPOKEN_AMOUNT, _parse_amount

    data = chat_json(prompt=text, schema=ENTRY_SCHEMA, system=ENTRY_SYSTEM)
    earned, spent = data.get("earned"), data.get("spent")

    if earned is None or spent is None:
        amounts = [a for m in _SPOKEN_AMOUNT.finditer(text) if (a := _parse_amount(m))]
        spend_words = re.compile(
            r"maal|saman|kharch|kharida|liya|stock|माल|सामान|खर्च|ख़र्च|खरीद|लिया",
            re.IGNORECASE,
        )
        # Two figures in one sentence is the common shape: takings first, then
        # what was spent on stock.
        if len(amounts) >= 2 and earned is None and spent is None:
            earned, spent = amounts[0], amounts[1]
        elif len(amounts) == 1 and earned is None and spent is None:
            if spend_words.search(text):
                spent = amounts[0]
            else:
                earned = amounts[0]

    return earned, spent, (data.get("note") or "")


def record(user_id: str, text: str, on: date | None = None) -> Entry:
    """Store one evening's entry. Re-recording the same day replaces it."""
    _ensure_table()
    earned, spent, note = parse_entry(text)
    entry = Entry(
        on=on or date.today(), earned=earned, spent=spent,
        note=note, raw_text=text, source="voice",
    )

    with get_conn() as conn:
        conn.execute(
            """INSERT INTO ledger_entries
               (user_id, on_date, earned, spent, note, raw_text, source, corroborated, created_at)
               VALUES (?,?,?,?,?,?,?,?,?)
               ON CONFLICT(user_id, on_date, source) DO UPDATE SET
                 earned=excluded.earned, spent=excluded.spent,
                 note=excluded.note, raw_text=excluded.raw_text""",
            (user_id, entry.on.isoformat(), entry.earned, entry.spent, entry.note,
             entry.raw_text, entry.source, 0, datetime.now().isoformat(timespec="seconds")),
        )
    return entry


def add_upi_records(user_id: str, records: list[tuple[date, float]]) -> int:
    """
    Import UPI settlements and mark the spoken days they corroborate.

    PM SVANidhi pushes vendors onto digital payments and pays cashback for it,
    so a lot of them have a QR code. Where a spoken figure lines up with a real
    settlement, the statement can say so — and that is the difference between
    an assertion and evidence.
    """
    _ensure_table()
    matched = 0
    with get_conn() as conn:
        for on, amount in records:
            conn.execute(
                """INSERT INTO ledger_entries
                   (user_id, on_date, earned, source, corroborated, created_at)
                   VALUES (?,?,?,'upi',1,?)
                   ON CONFLICT(user_id, on_date, source) DO UPDATE SET earned=excluded.earned""",
                (user_id, on.isoformat(), amount, datetime.now().isoformat(timespec="seconds")),
            )
            # Within 20%: spoken takings include cash, so an exact match is not
            # expected and demanding one would corroborate almost nothing.
            spoken = conn.execute(
                "SELECT earned FROM ledger_entries WHERE user_id=? AND on_date=? AND source='voice'",
                (user_id, on.isoformat()),
            ).fetchone()
            if spoken and spoken["earned"] and amount:
                if abs(spoken["earned"] - amount) <= 0.2 * max(spoken["earned"], amount):
                    conn.execute(
                        "UPDATE ledger_entries SET corroborated=1 "
                        "WHERE user_id=? AND on_date=? AND source='voice'",
                        (user_id, on.isoformat()),
                    )
                    matched += 1
    return matched


def entries(user_id: str, days: int = STATEMENT_DAYS, as_of: date | None = None) -> list[Entry]:
    _ensure_table()
    end = as_of or date.today()
    start = end - timedelta(days=days - 1)
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT * FROM ledger_entries
               WHERE user_id=? AND source='voice' AND on_date BETWEEN ? AND ?
               ORDER BY on_date""",
            (user_id, start.isoformat(), end.isoformat()),
        ).fetchall()
    return [
        Entry(
            on=date.fromisoformat(r["on_date"]), earned=r["earned"], spent=r["spent"],
            note=r["note"] or "", raw_text=r["raw_text"] or "",
            source=r["source"], corroborated=bool(r["corroborated"]),
        )
        for r in rows
    ]


# ── the statement ────────────────────────────────────────────────────────────

def build_statement(
    user_id: str, days: int = STATEMENT_DAYS, as_of: date | None = None
) -> Statement:
    """Aggregate the spoken record into something a loan officer can read."""
    end = as_of or date.today()
    start = end - timedelta(days=days - 1)
    records = [e for e in entries(user_id, days, end) if e.earned is not None]

    if not records:
        return Statement(
            user_id=user_id, period_start=start, period_end=end,
            days_covered=0, days_in_period=days, coverage_pct=0.0,
            total_earned=0.0, total_spent=0.0, net=0.0,
            median_daily_earned=0.0, best_day=0.0, worst_day=0.0,
            provenance="self-reported, spoken daily",
            corroboration_pct=0.0, confidence="indicative",
            caveats=["No entries recorded for this period."],
        )

    earnings = [e.earned for e in records]
    spending = [e.spent or 0.0 for e in records]
    covered = len(records)
    coverage = covered / days
    corroborated = sum(1 for e in records if e.corroborated)
    corroboration = corroborated / covered

    caveats: list[str] = []

    if covered < days:
        caveats.append(
            f"Covers {covered} of {days} days. Figures for days with no entry "
            f"are not estimated or filled in."
        )

    if corroborated:
        caveats.append(
            f"{corroborated} of {covered} days match a UPI settlement within 20%. "
            f"The rest are the vendor's own account."
        )
    else:
        caveats.append("No UPI records supplied, so nothing here is independently corroborated.")

    # Implausible smoothness. Real takings vary; a flat line is either a very
    # unusual business or a number someone made up. We say which we suspect and
    # let the lender decide.
    if covered >= 7:
        spread = statistics.pstdev(earnings) / (statistics.mean(earnings) or 1)
        if spread < 0.05:
            caveats.append(
                "Daily takings vary by under 5%, which is unusually flat for street "
                "vending. Worth asking about before relying on these figures."
            )

    if covered >= MIN_DAYS_FOR_CONFIDENCE and corroboration >= 0.5:
        confidence = "strong"
    elif covered >= MIN_DAYS_FOR_CONFIDENCE:
        confidence = "reasonable"
    else:
        confidence = "indicative"
        caveats.append(
            f"Fewer than {MIN_DAYS_FOR_CONFIDENCE} days recorded — indicative only, "
            f"not a basis for a lending decision on its own."
        )

    return Statement(
        user_id=user_id, period_start=start, period_end=end,
        days_covered=covered, days_in_period=days, coverage_pct=round(coverage, 3),
        total_earned=round(sum(earnings), 2),
        total_spent=round(sum(spending), 2),
        net=round(sum(earnings) - sum(spending), 2),
        median_daily_earned=round(statistics.median(earnings), 2),
        best_day=round(max(earnings), 2),
        worst_day=round(min(earnings), 2),
        provenance="self-reported by the vendor, spoken daily, transcribed on device",
        corroboration_pct=round(corroboration, 3),
        confidence=confidence,
        caveats=caveats,
        daily=[
            {
                "date": e.on.isoformat(),
                "earned": e.earned,
                "spent": e.spent,
                "corroborated": e.corroborated,
            }
            for e in records
        ],
    )


def statement_dict(statement: Statement) -> dict[str, Any]:
    data = statement.__dict__.copy()
    data["period_start"] = statement.period_start.isoformat()
    data["period_end"] = statement.period_end.isoformat()
    return data


def render_text(statement: Statement) -> str:
    """
    A plain-text statement.

    Deliberately not a styled PDF: the provenance block has to be as prominent
    as the totals, and a document that looks like a bank statement invites
    being read as one.
    """
    s = statement
    lines = [
        "CASH-FLOW STATEMENT",
        f"Prepared by Setu for user {s.user_id}",
        f"Period: {s.period_start} to {s.period_end}",
        "",
        "SOURCE OF FIGURES",
        f"  {s.provenance}",
        f"  Days covered:   {s.days_covered} of {s.days_in_period}  ({s.coverage_pct*100:.0f}%)",
        f"  Corroborated:   {s.corroboration_pct*100:.0f}% against UPI settlements",
        f"  Confidence:     {s.confidence.upper()}",
        "",
        "SUMMARY",
        f"  Total taken in:      Rs {s.total_earned:,.0f}",
        f"  Total spent:         Rs {s.total_spent:,.0f}",
        f"  Net:                 Rs {s.net:,.0f}",
        f"  Median day:          Rs {s.median_daily_earned:,.0f}",
        f"  Best / worst day:    Rs {s.best_day:,.0f} / Rs {s.worst_day:,.0f}",
        "",
        "WHAT THIS IS AND IS NOT",
    ]
    lines += [f"  - {c}" for c in s.caveats]
    lines += [
        "",
        "  This is a record of what the vendor reported, not a verified account.",
        "  It is offered so a lender has something to assess where previously",
        "  there was nothing at all.",
        "",
        "DAILY RECORD",
        f"  {'date':<12} {'earned':>9} {'spent':>9}  corroborated",
    ]
    for row in s.daily:
        spent = f"{row['spent']:,.0f}" if row["spent"] is not None else "-"
        lines.append(
            f"  {row['date']:<12} {row['earned']:>9,.0f} {spent:>9}  "
            f"{'yes' if row['corroborated'] else ''}"
        )
    return "\n".join(lines)


def seed_demo(user_id: str = "demo", days: int = STATEMENT_DAYS, as_of: date | None = None) -> int:
    """
    Thirty days of plausible takings, for demonstrating the statement without
    waiting a month.

    Noisy on purpose: Sundays busy, a two-day washout for rain, one festival
    spike. A flat series would trip the smoothness caveat, which would be a
    fitting thing for a fake ledger to do but a poor demo.
    """
    import random

    _ensure_table()
    rng = random.Random(20260809)
    end = as_of or date.today()
    written = 0

    with get_conn() as conn:
        for offset in range(days):
            day = end - timedelta(days=days - 1 - offset)

            # He does not speak every single night.
            if rng.random() < 0.18:
                continue

            base = 780
            if day.weekday() == 6:
                base *= 1.35            # Sunday
            if offset in (11, 12):
                base *= 0.35            # rain
            if offset == 22:
                base *= 1.8             # festival
            earned = round(base * rng.uniform(0.82, 1.18) / 10) * 10
            spent = round(earned * rng.uniform(0.22, 0.34) / 10) * 10

            conn.execute(
                """INSERT INTO ledger_entries
                   (user_id, on_date, earned, spent, note, raw_text, source, corroborated, created_at)
                   VALUES (?,?,?,?,?,?,'voice',0,?)
                   ON CONFLICT(user_id, on_date, source) DO UPDATE SET
                     earned=excluded.earned, spent=excluded.spent""",
                (user_id, day.isoformat(), earned, spent, "",
                 f"aaj {earned:.0f} ka kaam hua, {spent:.0f} ka maal liya",
                 datetime.now().isoformat(timespec="seconds")),
            )
            written += 1

    # Roughly half the days also went through UPI, which is what makes the
    # corroboration figure non-zero and the statement worth more.
    upi = [
        (date.fromisoformat(e["date"]), e["earned"] * rng.uniform(0.85, 1.0))
        for e in build_statement(user_id, days, end).daily
        if rng.random() < 0.55
    ]
    add_upi_records(user_id, upi)
    return written
