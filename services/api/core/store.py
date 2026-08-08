"""
Case store.

Ported from Sanvi's agent.py — her table design (queries / reminders /
user_profile) was right; this version stores our typed Decision objects and
tracks coverage gaps.

Deliberately SQLite and deliberately no scheduler: a `due_at` column plus a
"run due items now" endpoint is everything the demo needs, and one fewer moving
part at 3am.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from .schemas import Decision, EligibilityStatus, Profile

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "setu.db"


def get_conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS queries (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            query_id     TEXT,
            timestamp    TEXT,
            user_id      TEXT,
            query_text   TEXT,
            language     TEXT,
            profile_json TEXT,
            decisions_json TEXT,
            matched      INTEGER DEFAULT 0,
            fingerprint  TEXT
        );

        CREATE TABLE IF NOT EXISTS cases (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     TEXT,
            scheme_id   TEXT,
            scheme_name TEXT,
            status      TEXT DEFAULT 'open',
            step_order  INTEGER DEFAULT 1,
            action      TEXT,
            due_at      TEXT,
            completed_at TEXT,
            created_at  TEXT
        );

        CREATE TABLE IF NOT EXISTS user_profile (
            user_id      TEXT PRIMARY KEY,
            profile_json TEXT,
            updated_at   TEXT
        );

        -- Unmatched needs. This is the Demand Signal: aggregated, it becomes a
        -- policy brief showing what people ask for that no scheme covers.
        CREATE TABLE IF NOT EXISTS coverage_gaps (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp  TEXT,
            query_text TEXT,
            occupation TEXT,
            state      TEXT,
            need       TEXT
        );
        """
    )
    conn.commit()
    return conn


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def log_query(
    query_id: str,
    user_id: str,
    text: str,
    language: str,
    profile: Profile,
    decisions: list[Decision],
    fingerprint: str,
) -> None:
    matched = any(
        d.status is EligibilityStatus.ELIGIBLE or d.ladder for d in decisions
    )

    with get_conn() as conn:
        conn.execute(
            """INSERT INTO queries
               (query_id, timestamp, user_id, query_text, language,
                profile_json, decisions_json, matched, fingerprint)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (
                query_id, _now(), user_id, text, language,
                profile.model_dump_json(),
                json.dumps([d.model_dump(mode="json") for d in decisions]),
                int(matched), fingerprint,
            ),
        )
        conn.execute(
            """INSERT INTO user_profile (user_id, profile_json, updated_at)
               VALUES (?,?,?)
               ON CONFLICT(user_id) DO UPDATE SET
                 profile_json=excluded.profile_json, updated_at=excluded.updated_at""",
            (user_id, profile.model_dump_json(), _now()),
        )

        if not matched:
            conn.execute(
                """INSERT INTO coverage_gaps (timestamp, query_text, occupation, state, need)
                   VALUES (?,?,?,?,?)""",
                (_now(), text, profile.occupation, profile.state, profile.stated_need),
            )


def open_case(user_id: str, decision: Decision) -> int:
    """Turn a ladder into tracked, dated commitments — the follow-through."""
    if not decision.ladder:
        return 0

    created = 0
    with get_conn() as conn:
        for step in decision.ladder:
            due = (date.today() + timedelta(days=step.time_days or 7)).isoformat()
            conn.execute(
                """INSERT INTO cases
                   (user_id, scheme_id, scheme_name, status, step_order, action, due_at, created_at)
                   VALUES (?,?,?,'open',?,?,?,?)""",
                (user_id, decision.scheme_id, decision.scheme_name,
                 step.order, step.action, due, _now()),
            )
            created += 1
    return created


def due_cases(as_of: str | None = None) -> list[dict[str, Any]]:
    cutoff = as_of or date.today().isoformat()
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM cases WHERE status='open' AND due_at <= ? ORDER BY due_at",
            (cutoff,),
        ).fetchall()
    return [dict(r) for r in rows]


def complete_case(case_id: int) -> None:
    with get_conn() as conn:
        conn.execute(
            "UPDATE cases SET status='done', completed_at=? WHERE id=?", (_now(), case_id)
        )


def recent_queries(limit: int = 50) -> list[dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM queries ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(r) for r in rows]


def coverage_gaps(limit: int = 50) -> list[dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT need, occupation, state, COUNT(*) AS requests
               FROM coverage_gaps GROUP BY need, occupation, state
               ORDER BY requests DESC LIMIT ?""",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


def stats() -> dict[str, Any]:
    with get_conn() as conn:
        total = conn.execute("SELECT COUNT(*) c FROM queries").fetchone()["c"]
        matched = conn.execute("SELECT COUNT(*) c FROM queries WHERE matched=1").fetchone()["c"]
        users = conn.execute("SELECT COUNT(*) c FROM user_profile").fetchone()["c"]
        open_cases = conn.execute("SELECT COUNT(*) c FROM cases WHERE status='open'").fetchone()["c"]
        gaps = conn.execute("SELECT COUNT(*) c FROM coverage_gaps").fetchone()["c"]

    return {
        "queries": total,
        "matched": matched,
        "match_rate": round(matched / total, 3) if total else 0.0,
        "users": users,
        "open_cases": open_cases,
        "coverage_gaps": gaps,
    }
