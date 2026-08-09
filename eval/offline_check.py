"""
Airplane-mode verification.

    .venv/bin/python eval/offline_check.py

Blocks every socket except loopback, then exercises the whole demo path. This
is what the venue wifi failing actually looks like: Ollama still answers on
127.0.0.1, and nothing else is reachable.

Run this before the demo. A path that quietly needs the network will pass every
other test you have and fail in the one room where it matters.
"""

from __future__ import annotations

import socket
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

_LOOPBACK = {"127.0.0.1", "::1", "localhost", "0.0.0.0"}


class NetworkBlocked(OSError):
    """Raised instead of reaching the internet."""


def cut_the_wire() -> None:
    """
    Allow loopback, refuse everything else.

    Patching at the socket layer catches every client library at once — httpx,
    requests, aiohttp, urllib, and whatever edge-tts uses internally — which
    grepping for imports would not.
    """
    real_connect = socket.socket.connect
    real_connect_ex = socket.socket.connect_ex
    real_getaddrinfo = socket.getaddrinfo

    def guard(address):
        host = address[0] if isinstance(address, tuple) else str(address)
        if host not in _LOOPBACK:
            raise NetworkBlocked(f"offline: refused connection to {host}")

    def patched_connect(self, address):
        guard(address)
        return real_connect(self, address)

    def patched_connect_ex(self, address):
        try:
            guard(address)
        except NetworkBlocked:
            return 111  # ECONNREFUSED
        return real_connect_ex(self, address)

    def patched_getaddrinfo(host, *args, **kwargs):
        if host not in _LOOPBACK:
            raise NetworkBlocked(f"offline: refused DNS lookup for {host}")
        return real_getaddrinfo(host, *args, **kwargs)

    socket.socket.connect = patched_connect
    socket.socket.connect_ex = patched_connect_ex
    socket.getaddrinfo = patched_getaddrinfo


results: list[tuple[str, bool, str, float]] = []


def check(name: str, critical: bool = True):
    """Run one step, record what happened, never abort the sweep."""
    def decorator(fn):
        start = time.perf_counter()
        try:
            detail = fn() or "ok"
            ok = True
        except Exception as exc:  # noqa: BLE001
            ok = False
            detail = f"{type(exc).__name__}: {exc}"
            if "--trace" in sys.argv:
                traceback.print_exc()
        results.append((name, ok, str(detail)[:120], (time.perf_counter() - start) * 1000))
        if not ok and critical:
            print(f"  ✗ {name}: {detail}")
        return fn
    return decorator


DEMO_TEXT = (
    "Main 34 saal ka hoon, Bangalore mein pani puri ka thela chalata hoon. "
    "Saat saal se yeh kaam kar raha hoon. Roz kareeb aath sau rupaye ka dhandha "
    "hota hai. Mere paas Aadhaar card aur bank passbook hai, lekin vending "
    "certificate nahi hai."
)


def main() -> int:
    print("\n  Cutting the wire — loopback only, everything else refused.\n")
    cut_the_wire()

    from services.api.core import (  # noqa: E402
        doc_doctor, eligibility, llm, narrate, pathfinder, rag, store, voice,
    )
    from services.api.core import profile as profile_mod  # noqa: E402

    state: dict = {}

    @check("Ollama reachable on localhost")
    def _():
        health = llm.health()
        if not health["reachable"]:
            raise RuntimeError(health.get("error", "unreachable"))
        return f"{health['chat_model']} + {health['embed_model']}"

    @check("Chroma index loads from disk")
    def _():
        stats = rag.stats()
        if not stats["chunks"]:
            raise RuntimeError("index is empty")
        return f"{stats['chunks']} chunks, {len(stats['documents'])} documents"

    @check("Retrieval returns a citation")
    def _():
        hits = rag.search("certificate of vending letter of recommendation", k=1)
        if not hits:
            raise RuntimeError("no results")
        return f"{hits[0].source_doc} p{hits[0].page_no}"

    @check("Profile extraction (the demo sentence)")
    def _():
        state["profile"] = profile_mod.extract(DEMO_TEXT)
        p = state["profile"]
        if not p.occupation_category:
            raise RuntimeError("occupation not extracted")
        return f"age={p.age} {p.occupation_category} docs={len(p.documents)}"

    @check("Eligibility + ladder")
    def _():
        decisions = pathfinder.build_all(
            state["profile"], eligibility.evaluate_all(state["profile"])
        )
        state["decisions"] = decisions
        laddered = [d for d in decisions if d.ladder]
        if not laddered:
            raise RuntimeError("no ladder produced for the demo persona")
        if not all(pathfinder.verify_ladder(state["profile"], d) for d in laddered):
            raise RuntimeError("a ladder does not reach eligibility")
        return f"{len(decisions)} schemes, {len(laddered[0].ladder)} rungs verified"

    @check("Narration in Hindi")
    def _():
        state["spoken"] = narrate.narrate_all(state["profile"], state["decisions"], "hi")
        if not state["spoken"].strip():
            raise RuntimeError("empty narration")
        return f"{len(state['spoken'].split())} words"

    @check("Text to speech")
    def _():
        path = voice.speak(state["spoken"], "hi")
        size = Path(path).stat().st_size
        if size == 0:
            raise RuntimeError("zero-byte audio")
        return f"{Path(path).name} ({size // 1024} KB)"

    @check("Text to speech — UNCACHED text", critical=False)
    def _():
        """
        The one genuine offline limitation, and it must not hide behind a cache
        hit. edge-tts synthesises through Microsoft, so a sentence nobody has
        spoken before cannot be voiced with the wire cut.

        This is survivable: /api/reason catches the failure and returns the text
        without audio, so the answer still appears. It only bites if a judge
        types something novel AND you are offline AND the spoken answer is the
        moment you are selling. Pre-cache every line you plan to demo.
        """
        novel = f"offline probe {time.time()}"
        try:
            voice.speak(novel, "hi")
            return "unexpectedly worked — a local TTS engine must be installed"
        except voice.VoiceError:
            raise RuntimeError(
                "expected: edge-tts needs the network. Cached lines are fine; "
                "novel text degrades to text-only."
            ) from None

    @check("Speech to text (Whisper)")
    def _():
        cached = sorted(voice.CACHE_DIR.glob("*.mp3"))
        if not cached:
            raise RuntimeError("no cached audio to transcribe")
        text = voice.transcribe(cached[0], language="hi")
        if not text.strip():
            raise RuntimeError("empty transcription")
        return f"{len(text.split())} words back"

    @check("Case store writes")
    def _():
        laddered = next(d for d in state["decisions"] if d.ladder)
        created = store.open_case("offline_check", laddered)
        return f"{created} steps tracked"

    @check("Document reading (vision)", critical=False)
    def _():
        samples = sorted(Path("/tmp/docs2").glob("*.png")) if Path("/tmp/docs2").exists() else []
        if len(samples) < 2:
            return "skipped — no sample cards on disk"
        report = doc_doctor.review([(p, None) for p in samples[:2]])
        return f"reliable={report['reading_is_reliable']}, {len(report['findings'])} finding(s)"

    # ── report ───────────────────────────────────────────────────────────────
    print("=" * 70)
    print("  OFFLINE VERIFICATION")
    print("=" * 70 + "\n")
    for name, ok, detail, ms in results:
        print(f"  {'✓' if ok else '✗'}  {name:<38} {ms:7.0f}ms  {detail}")

    critical_names = {
        "Ollama reachable on localhost", "Chroma index loads from disk",
        "Retrieval returns a citation", "Profile extraction (the demo sentence)",
        "Eligibility + ladder", "Narration in Hindi", "Text to speech",
        "Speech to text (Whisper)", "Case store writes",
    }
    failed = [r for r in results if not r[1] and r[0] in critical_names]
    known = [r for r in results if not r[1] and r[0] not in critical_names]

    if known:
        print("\n  Known limitations (not blockers):")
        for name, _ok, detail, _ms in known:
            print(f"    · {name}\n      {detail}")

    print()
    if failed:
        print(f"  {len(failed)} step(s) FAILED offline:\n")
        for name, _ok, detail, _ms in failed:
            print(f"    {name}\n      {detail}\n")
        print("  Fix these before the demo, or run with the network up and")
        print("  accept that the venue wifi is now load-bearing.\n")
        return 1

    total = sum(r[3] for r in results)
    print(f"  Every critical step passed with the wire cut. Total {total:.0f}ms.")
    print("  Note: the timings above include cold model loads. The server warms")
    print("  Granite, Whisper and the vision model at startup — start it before")
    print("  the demo, not during it.\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
