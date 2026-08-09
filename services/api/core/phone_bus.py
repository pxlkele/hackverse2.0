"""
Tiny in-process pub/sub for phone events.

The Twilio webhook publishes what the caller said; the console subscribes
via SSE and mirrors the transcript into its input textarea in real time.
"""

from __future__ import annotations

import asyncio
from typing import Any

_subs: set[asyncio.Queue] = set()


def subscribe() -> asyncio.Queue:
    q: asyncio.Queue = asyncio.Queue(maxsize=32)
    _subs.add(q)
    return q


def unsubscribe(q: asyncio.Queue) -> None:
    _subs.discard(q)


def publish(event: dict[str, Any]) -> None:
    for q in list(_subs):
        try:
            q.put_nowait(event)
        except asyncio.QueueFull:
            pass  # slow subscriber; drop
