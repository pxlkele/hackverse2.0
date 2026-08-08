"""
Setu - backend API.

This is what a future voice layer (ASR -> here -> TTS) and the dashboard both
call. Keeping it thin: real logic lives in agent.py / rag.py.

Run:
    uvicorn backend.main:app --reload --port 8000
"""
from fastapi import FastAPI
from pydantic import BaseModel

from backend import agent

app = FastAPI(title="Setu backend")


class QueryRequest(BaseModel):
    user_id: str
    text: str


class ReminderRequest(BaseModel):
    user_id: str
    scheme: str
    due_date: str


@app.post("/query")
def query(req: QueryRequest):
    return agent.process_query(req.user_id, req.text)


@app.get("/logs")
def logs(limit: int = 50):
    conn = agent.get_conn()
    rows = conn.execute(
        "SELECT timestamp, user_id, query_text, answer_text, sources, confidence "
        "FROM queries ORDER BY id DESC LIMIT ?",
        (limit,),
    ).fetchall()
    conn.close()
    cols = ["timestamp", "user_id", "query_text", "answer_text", "sources", "confidence"]
    return [dict(zip(cols, r)) for r in rows]


@app.post("/reminders")
def create_reminder(req: ReminderRequest):
    agent.add_reminder(req.user_id, req.scheme, req.due_date)
    return {"status": "ok"}


@app.get("/reminders/due")
def reminders_due():
    rows = agent.due_reminders()
    return [{"id": r[0], "user_id": r[1], "scheme": r[2], "due_date": r[3]} for r in rows]


@app.get("/profile/{user_id}")
def profile(user_id: str):
    return {"user_id": user_id, "matched_schemes": agent.get_profile(user_id)}
