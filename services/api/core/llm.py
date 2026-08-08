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

# Granite is well-behaved about JSON but not perfectly — it occasionally wraps
# output in a markdown fence. Cheaper to strip that than to retry the call.
_FENCE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.MULTILINE)


class LLMError(RuntimeError):
    pass


def chat(prompt: str, system: str | None = None, temperature: float = 0.0) -> str:
    """Plain text completion."""
    if BACKEND != "ollama":
        raise LLMError(f"backend '{BACKEND}' not wired up yet")

    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    with httpx.Client(timeout=TIMEOUT) as client:
        response = client.post(
            f"{OLLAMA_URL}/api/chat",
            json={
                "model": CHAT_MODEL,
                "messages": messages,
                "stream": False,
                "options": {"temperature": temperature},
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
            json={"model": EMBED_MODEL, "prompt": text},
        )
        response.raise_for_status()
        return response.json()["embedding"]


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
