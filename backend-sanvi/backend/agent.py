"""
Setu - Agentic layer.

Chains: eligibility check (via rag.answer) -> log -> update the user's
financial-identity profile (for proactive re-matching later) -> reminders.

State lives in SQLite so the dashboard can show live query history and due
reminders without a separate service.
"""
import os
import sqlite3
import json
import datetime

from backend import rag

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "setu.db")


def get_conn():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS queries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT,
            user_id TEXT,
            query_text TEXT,
            answer_text TEXT,
            sources TEXT,
            confidence TEXT,
            matched INTEGER DEFAULT 0
        )
    """)
    # defensive migration in case an older DB from before `matched` existed is on disk
    try:
        conn.execute("ALTER TABLE queries ADD COLUMN matched INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass  # column already exists
    conn.execute("""
        CREATE TABLE IF NOT EXISTS reminders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT,
            scheme TEXT,
            due_date TEXT,
            status TEXT DEFAULT 'pending',
            created_at TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS user_profile (
            user_id TEXT PRIMARY KEY,
            matched_schemes TEXT
        )
    """)
    conn.commit()
    return conn


def _extract_confidence(answer_text: str) -> str:
    for level in ("High", "Medium", "Low"):
        if f"Confidence: {level}" in answer_text or f"Confidence: [{level}]" in answer_text:
            return level
    return "Unknown"


def process_query(user_id: str, query_text: str):
    """Full agentic chain: RAG answer -> log -> update profile."""
    result = rag.answer(query_text)
    confidence = _extract_confidence(result["answer"])
    matched = 1 if result["sources"] else 0

    conn = get_conn()
    conn.execute(
        "INSERT INTO queries (timestamp, user_id, query_text, answer_text, sources, confidence, matched) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            datetime.datetime.utcnow().isoformat(),
            user_id,
            query_text,
            result["answer"],
            json.dumps(result["sources"]),
            confidence,
            matched,
        ),
    )

    if matched:
        row = conn.execute(
            "SELECT matched_schemes FROM user_profile WHERE user_id=?", (user_id,)
        ).fetchone()
        existing = json.loads(row[0]) if row else []
        updated = sorted(set(existing) | set(result["sources"]))
        conn.execute(
            "INSERT INTO user_profile (user_id, matched_schemes) VALUES (?, ?) "
            "ON CONFLICT(user_id) DO UPDATE SET matched_schemes=excluded.matched_schemes",
            (user_id, json.dumps(updated)),
        )
    conn.commit()
    conn.close()

    return {**result, "confidence": confidence, "matched": bool(matched)}


def add_reminder(user_id: str, scheme: str, due_date: str):
    conn = get_conn()
    conn.execute(
        "INSERT INTO reminders (user_id, scheme, due_date, created_at) VALUES (?, ?, ?, ?)",
        (user_id, scheme, due_date, datetime.datetime.utcnow().isoformat()),
    )
    conn.commit()
    conn.close()


def due_reminders():
    conn = get_conn()
    rows = conn.execute(
        "SELECT id, user_id, scheme, due_date FROM reminders "
        "WHERE status='pending' AND due_date <= ? ORDER BY due_date",
        (datetime.date.today().isoformat(),),
    ).fetchall()
    conn.close()
    return rows


def get_profile(user_id: str):
    conn = get_conn()
    row = conn.execute(
        "SELECT matched_schemes FROM user_profile WHERE user_id=?", (user_id,)
    ).fetchone()
    conn.close()
    return json.loads(row[0]) if row else []


def stats():
    """Aggregates for the dashboard's Overview tab: volume, match rate,
    confidence mix, top matched schemes, and coverage gaps (queries Setu
    couldn't ground in any indexed doc - these are what should drive which
    scheme docs you source next)."""
    conn = get_conn()
    total = conn.execute("SELECT COUNT(*) FROM queries").fetchone()[0]
    matched = conn.execute("SELECT COUNT(*) FROM queries WHERE matched=1").fetchone()[0]

    confidence_rows = conn.execute(
        "SELECT confidence, COUNT(*) FROM queries GROUP BY confidence"
    ).fetchall()

    source_rows = conn.execute("SELECT sources FROM queries WHERE matched=1").fetchall()
    scheme_counts = {}
    for (sources_json,) in source_rows:
        for s in json.loads(sources_json):
            scheme_counts[s] = scheme_counts.get(s, 0) + 1

    gap_rows = conn.execute(
        "SELECT timestamp, user_id, query_text FROM queries WHERE matched=0 "
        "ORDER BY id DESC LIMIT 20"
    ).fetchall()
    conn.close()

    return {
        "total_queries": total,
        "matched_queries": matched,
        "match_rate": (matched / total) if total else 0.0,
        "confidence_breakdown": dict(confidence_rows),
        "top_schemes": sorted(scheme_counts.items(), key=lambda x: -x[1]),
        "coverage_gaps": [
            {"timestamp": r[0], "user_id": r[1], "query_text": r[2]} for r in gap_rows
        ],
    }
