"""
Setu — operator console.

    streamlit run apps/dashboard/app.py

Two tabs, two audiences:
  Ask Setu — what a CSC operator or Bank Mitra sees while helping someone.
             The vendor never sees this; he only hears the audio at the end.
  Impact   — evidence for the pitch: match rate, coverage gaps.

The reasoning panel reveals real rule evaluations one at a time. Nothing here
is staged — every tick is a rule that actually fired, with the government
document it came from. The pacing exists so a human can read it, not to
manufacture suspense.
"""

from __future__ import annotations

import time
from pathlib import Path

import httpx
import pandas as pd
import streamlit as st

API = "http://localhost:8000/api"
REVEAL_DELAY = 0.35  # seconds per line — readable without dragging

st.set_page_config(page_title="Setu", page_icon="🪜", layout="wide")

st.markdown(
    """
    <style>
      .rule-pass { color:#1a7f37; font-weight:600; }
      .rule-fail { color:#b3261e; font-weight:600; }
      .rule-unknown { color:#8a6d00; font-weight:600; }
      .cite { color:#666; font-size:0.78rem; font-family:ui-monospace,monospace; }
      .rung { border-left:3px solid #1a7f37; padding:0.4rem 0 0.4rem 0.9rem; margin:0.5rem 0; }
      .big { font-size:1.6rem; font-weight:700; }
    </style>
    """,
    unsafe_allow_html=True,
)


def api_get(path: str, **params):
    try:
        return httpx.get(f"{API}{path}", params=params, timeout=30).json()
    except Exception as exc:  # noqa: BLE001
        st.error(f"API unreachable — is uvicorn running on :8000?  ({exc})")
        return None


def api_post(path: str, payload: dict, timeout: float = 180):
    try:
        return httpx.post(f"{API}{path}", json=payload, timeout=timeout).json()
    except Exception as exc:  # noqa: BLE001
        st.error(f"API error: {exc}")
        return None


tab_ask, tab_impact = st.tabs(["🎙  Ask Setu", "📊  Impact"])


# ── Tab 1: the demo ──────────────────────────────────────────────────────────

with tab_ask:
    st.markdown("### What did they say?")

    SAMPLES = {
        "Pani puri vendor, Bangalore (the demo)":
            "Main 34 saal ka hoon, Bangalore mein pani puri ka thela chalata hoon. "
            "Saat saal se yeh kaam kar raha hoon. Roz kareeb aath sau rupaye ka dhandha "
            "hota hai. Mere paas Aadhaar card aur bank passbook hai, lekin vending "
            "certificate nahi hai.",
        "Tailor, no documents":
            "Main darzi ka kaam karta hoon Pune mein. Mahine ka teen hazaar kamata hoon. "
            "Koi document nahi hai mere paas.",
        "Vendor with everything":
            "Main 40 saal ka hoon, Delhi mein chaat ka thela lagata hoon. Roz hazaar ka "
            "dhandha. Aadhaar, bank passbook, vending certificate aur PhonePe sab hai.",
    }

    choice = st.selectbox("Sample", list(SAMPLES) + ["— type my own —"])
    default = "" if choice == "— type my own —" else SAMPLES[choice]
    text = st.text_area("Their words", value=default, height=110, label_visibility="collapsed")

    col_a, col_b, _ = st.columns([1, 1, 3])
    lang = col_a.selectbox("Reply in", ["hi", "mr", "kn", "ta", "te", "bn", "en"])
    go = col_b.button("▶  Run", type="primary", use_container_width=True)

    if go and text.strip():
        panel = st.container()
        with panel:
            st.markdown("---")
            slot = st.empty()
            slot.markdown("🎙  **Listening…**")

            result = api_post("/reason", {"text": text, "language": lang})
            if not result:
                st.stop()

            slot.markdown("🧠  **Thinking…**")
            time.sleep(0.2)
            slot.empty()

            # ── the visible thought process ──────────────────────────────
            for step in result["steps"]:
                kind = step["kind"]

                if kind == "heard":
                    st.markdown(f"🧠  **{step['label']}** — {step['detail']}")

                elif kind == "scheme":
                    st.markdown("")
                    st.markdown(f"📋  **Checking {step['label']}** · {step['detail']}")

                elif kind == "rule":
                    mark, cls = {
                        True:  ("✓", "rule-pass"),
                        False: ("✗", "rule-fail"),
                        None:  ("⋯", "rule-unknown"),
                    }[step["passed"]]
                    left, right = st.columns([3, 2])
                    left.markdown(
                        f"&nbsp;&nbsp;&nbsp;<span class='{cls}'>{mark}</span> {step['label']}",
                        unsafe_allow_html=True,
                    )
                    right.markdown(f"<span class='cite'>{step['citation']}</span>",
                                   unsafe_allow_html=True)
                    if step["quote"]:
                        with st.expander("Why?", expanded=False):
                            st.markdown(f"**Rule:** {step['expected']}")
                            st.markdown(f"**Theirs:** {step['actual']}")
                            st.info(f"“{step['quote']}”\n\n— {step['citation']}")

                elif kind == "ladder":
                    st.markdown("")
                    st.success(f"🪜  **{step['label']}** · {step['detail']}")
                    for rung in step["steps"]:
                        cost = "free" if rung["cost_rupees"] == 0 else f"₹{rung['cost_rupees']:.0f}"
                        st.markdown(
                            f"<div class='rung'><b>{rung['order']}. {rung['action']}</b><br>"
                            f"<span class='cite'>{cost} · {rung['time_days']} days · {rung['where']}</span><br>"
                            f"{rung['detail']}</div>",
                            unsafe_allow_html=True,
                        )
                time.sleep(REVEAL_DELAY)

            # ── the answer he actually receives ──────────────────────────
            st.markdown("---")
            st.markdown("### 🔊  What he hears")
            st.caption("He has no screen. This is the entire product from his side.")
            st.markdown(f"<div class='big'>{result['spoken_text']}</div>", unsafe_allow_html=True)

            audio = result.get("audio_path")
            if audio and Path(audio).exists():
                st.audio(audio, autoplay=True)
            else:
                st.warning("No audio — TTS unavailable. Text shown above.")

            t = result["timings_ms"]
            st.caption(
                f"trace `{result['trace_fingerprint']}` · "
                + " · ".join(f"{k.replace('_ms','')} {v:.0f}ms" for k, v in t.items())
                + f" · total {sum(t.values()):.0f}ms"
            )


# ── Tab 2: evidence ──────────────────────────────────────────────────────────

with tab_impact:
    stats = api_get("/stats")
    health = api_get("/health")

    if stats:
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("People helped", stats["users"])
        c2.metric("Queries", stats["queries"])
        c3.metric("Match rate", f"{stats['match_rate']*100:.0f}%")
        c4.metric("Open cases", stats["open_cases"])

    if health:
        idx = health["index"]
        st.caption(
            f"Knowledge base: {idx['chunks']} chunks · {len(idx['documents'])} government "
            f"documents · {len(idx['schemes'])} schemes · embeddings "
            f"{health['llm']['embed_model']} · reasoning {health['llm']['chat_model']}"
        )

    st.markdown("#### Coverage gaps")
    st.caption(
        "Needs no scheme covered. Aggregated, this is a demand signal for "
        "policymakers — what people ask for that nothing currently answers."
    )
    gaps = api_get("/gaps")
    if gaps:
        st.dataframe(pd.DataFrame(gaps), use_container_width=True, hide_index=True)
    else:
        st.info("No gaps recorded yet — every query so far matched a scheme.")

    st.markdown("#### Recent queries")
    logs = api_get("/logs", limit=25)
    if logs:
        df = pd.DataFrame(logs)[["timestamp", "query_text", "matched", "fingerprint"]]
        st.dataframe(df, use_container_width=True, hide_index=True)
