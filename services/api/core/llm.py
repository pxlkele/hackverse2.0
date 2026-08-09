"""
Granite adapter.

Ollama today, watsonx.ai later — swap with one env var, no caller changes.

    SETU_LLM_BACKEND=ollama | watsonx
"""

from __future__ import annotations

import json
import os
import re
from typing import Any

import httpx

OLLAMA_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
CHAT_MODEL = os.getenv("SETU_CHAT_MODEL", "granite4:tiny-h")
EMBED_MODEL = os.getenv("SETU_EMBED_MODEL", "granite-embedding:278m")
BACKEND = os.getenv("SETU_LLM_BACKEND", "ollama")

TIMEOUT = httpx.Timeout(120.0, connect=10.0)

# Keep both models resident. Without this Ollama evicts one model to load the
# other on every request, and a query that should take 3s takes 30 — the chat
# and embedding models are used back-to-back on every single query.
KEEP_ALIVE = os.getenv("SETU_KEEP_ALIVE", "30m")

# Granite is well-behaved about JSON but not perfectly — it occasionally wraps
# output in a markdown fence. Cheaper to strip that than to retry the call.
_FENCE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.MULTILINE)


class LLMError(RuntimeError):
    pass


def chat(
    prompt: str,
    system: str | None = None,
    temperature: float = 0.0,
    max_tokens: int | None = None,
) -> str:
    """
    Plain text completion.

    `max_tokens` caps generation (Ollama's num_predict). This machine has no
    GPU and Granite runs at roughly 10 tokens per second, so an answer's length
    *is* its latency — and an uncapped call can run away entirely: pre-caching
    the Gujarati narrations died on a single request that never came back
    inside the 120s timeout. Callers that know how long an answer should be
    should say so. Left as None, behaviour is unchanged.
    """
    if BACKEND != "ollama":
        raise LLMError(f"backend '{BACKEND}' not wired up yet")

    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    options: dict[str, Any] = {"temperature": temperature}
    if max_tokens is not None:
        options["num_predict"] = max_tokens

    with httpx.Client(timeout=TIMEOUT) as client:
        response = client.post(
            f"{OLLAMA_URL}/api/chat",
            json={
                "model": CHAT_MODEL,
                "messages": messages,
                "stream": False,
                "keep_alive": KEEP_ALIVE,
                "options": options,
            },
        )
        response.raise_for_status()
        return response.json()["message"]["content"]


def chat_multi(
    messages: list[dict[str, str]],
    temperature: float = 0.2,
    max_tokens: int | None = None,
) -> str:
    """
    Multi-turn chat. `messages` is a list of {"role": "system"|"user"|"assistant",
    "content": str} in order — used by the follow-up chat mode in ivr_sim so a
    caller can ask "which docs?", "where do I go?" after the initial answer.

    Same latency profile as chat() but with a full history the model can see.
    """
    if BACKEND != "ollama":
        raise LLMError(f"backend '{BACKEND}' not wired up yet")

    options: dict[str, Any] = {"temperature": temperature}
    if max_tokens is not None:
        options["num_predict"] = max_tokens

    with httpx.Client(timeout=TIMEOUT) as client:
        response = client.post(
            f"{OLLAMA_URL}/api/chat",
            json={
                "model": CHAT_MODEL,
                "messages": messages,
                "stream": False,
                "keep_alive": KEEP_ALIVE,
                "options": options,
            },
        )
        response.raise_for_status()
        return response.json()["message"]["content"]


def chat_json(
    prompt: str,
    schema: dict[str, Any] | None = None,
    system: str | None = None,
    retries: int = 2,
) -> dict[str, Any]:
    """
    Completion constrained to JSON.

    Ollama's `format` accepts a JSON schema, which is far more reliable than
    asking politely in the prompt. We still retry on parse failure because a
    malformed profile should never reach the rule engine.
    """
    if BACKEND != "ollama":
        raise LLMError(f"backend '{BACKEND}' not wired up yet")

    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    payload: dict[str, Any] = {
        "model": CHAT_MODEL,
        "messages": messages,
        "stream": False,
        "keep_alive": KEEP_ALIVE,
        "options": {"temperature": 0.0},
        "format": schema if schema else "json",
    }

    last_error: Exception | None = None
    with httpx.Client(timeout=TIMEOUT) as client:
        for _ in range(retries + 1):
            try:
                response = client.post(f"{OLLAMA_URL}/api/chat", json=payload)
                response.raise_for_status()
                raw = response.json()["message"]["content"]
                return json.loads(_FENCE.sub("", raw).strip())
            except (json.JSONDecodeError, KeyError) as exc:
                last_error = exc
                continue

    raise LLMError(f"model did not return valid JSON after {retries + 1} tries: {last_error}")


def embed(text: str) -> list[float]:
    """Single embedding. Same model used at ingestion time — do not change one without the other."""
    with httpx.Client(timeout=TIMEOUT) as client:
        response = client.post(
            f"{OLLAMA_URL}/api/embeddings",
            json={"model": EMBED_MODEL, "prompt": text, "keep_alive": KEEP_ALIVE},
        )
        response.raise_for_status()
        return response.json()["embedding"]


def warm() -> None:
    """Load both models before the first real query. Call this at startup —
    the first call is always slow and on stage it looks like a hang."""
    try:
        chat("ok", temperature=0.0)
        embed("warm")
    except Exception:
        pass


def health() -> dict[str, Any]:
    """Is the model server actually up, and are our models present?"""
    try:
        with httpx.Client(timeout=httpx.Timeout(5.0)) as client:
            tags = client.get(f"{OLLAMA_URL}/api/tags").json()
        installed = {m["name"] for m in tags.get("models", [])}
        return {
            "backend": BACKEND,
            "reachable": True,
            "chat_model": CHAT_MODEL,
            "chat_model_present": CHAT_MODEL in installed,
            "embed_model": EMBED_MODEL,
            "embed_model_present": EMBED_MODEL in installed,
        }
    except Exception as exc:
        return {"backend": BACKEND, "reachable": False, "error": str(exc)}
