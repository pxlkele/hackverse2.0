"""
Setu - internal ops dashboard.

Doubles as: (1) your dev tool for watching RAG retrieval + Granite output
while you build, (2) your judge-facing demo screen once voice is wired in
(the "Try a query" tab is where the mic button will land), (3) a live view
of two things you're pitching as differentiators - coverage-gap learning and
proactive re-matching - so you can point at real numbers instead of just
describing them.

Run:
    streamlit run dashboard/app.py
"""
import os
import sys
import json
import pandas as pd
import streamlit as st

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))
from backend import agent, rag

st.set_page_config(page_title="Setu - Ops Dashboard", layout="wide")
st.title("Setu - Live Ops Dashboard")

tab_overview, tab_query, tab_logs, tab_reminders, tab_rematch = st.tabs(
    ["Overview", "Try a query", "Query log", "Reminders", "Re-match preview"]
)

# ---------------------------------------------------------------------------
# Overview
# ---------------------------------------------------------------------------
with tab_overview:
    st.subheader("Pipeline health")
    s = agent.stats()

    col1, col2, col3 = st.columns(3)
    col1.metric("Total queries", s["total_queries"])
    col2.metric("Matched", s["matched_queries"])
    col3.metric("Match rate", f"{s['match_rate'] * 100:.0f}%")

    c1, c2 = st.columns(2)

    with c1:
        st.markdown("**Confidence breakdown**")
        if s["confidence_breakdown"]:
            df_conf = pd.DataFrame(
                list(s["confidence_breakdown"].items()), columns=["confidence", "count"]
            ).set_index("confidence")
            st.bar_chart(df_conf)
        else:
            st.info("No queries yet.")

    with c2:
        st.markdown("**Top matched schemes**")
        if s["top_schemes"]:
            df_top = pd.DataFrame(s["top_schemes"], columns=["source", "matches"]).set_index(
                "source"
            )
            st.bar_chart(df_top)
        else:
            st.info("No matches yet.")

    st.markdown("---")
    st.markdown("**Coverage gaps** - queries Setu could NOT ground in any indexed doc. "
                "This is the queue for what real scheme docs to source next.")
    if s["coverage_gaps"]:
        st.dataframe(pd.DataFrame(s["coverage_gaps"]), use_container_width=True)
    else:
        st.info("No unmatched queries yet - either you're fully covered or nobody's tested edge cases.")

    st.markdown("---")
    st.markdown("**Knowledge base**")
    try:
        indexed = rag.list_indexed_sources()
    except Exception as e:
        indexed = []
        st.warning(f"Could not read Chroma collection: {e}")
    if indexed:
        st.write(f"{len(indexed)} document(s) indexed:")
        st.write(", ".join(indexed))
    else:
        st.warning("Nothing indexed yet. Run `python backend/ingest.py` after adding real scheme docs.")

# ---------------------------------------------------------------------------
# Try a query
# ---------------------------------------------------------------------------
with tab_query:
    st.subheader("Simulate a user query (text stand-in for voice input)")
    user_id = st.text_input("User ID", value="demo-user-1")
    query_text = st.text_area(
        "What is the user saying?", value="I run a tailoring shop, no loan history"
    )
    if st.button("Run through Setu"):
        with st.spinner("Retrieving + reasoning..."):
            try:
                result = agent.process_query(user_id, query_text)
            except Exception as e:
                st.error(f"Pipeline error: {e}")
                result = None
        if result:
            badge = "matched" if result.get("matched") else "no match"
            st.markdown(f"### Answer  `{badge}`")
            st.write(result["answer"])
            st.markdown(f"**Confidence:** {result['confidence']}")
            st.markdown(f"**Sources:** {', '.join(result['sources']) or 'none'}")
            with st.expander("Retrieved chunks (raw RAG hits)"):
                for h in result["hits"]:
                    st.markdown(f"**{h['source']}** (distance {h['distance']:.3f})")
                    st.text(h["text"][:500])

# ---------------------------------------------------------------------------
# Query log
# ---------------------------------------------------------------------------
with tab_logs:
    st.subheader("Recent queries")
    conn = agent.get_conn()
    rows = conn.execute(
        "SELECT timestamp, user_id, query_text, confidence, sources, matched "
        "FROM queries ORDER BY id DESC LIMIT 100"
    ).fetchall()
    conn.close()
    if rows:
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "time": r[0],
                        "user": r[1],
                        "query": r[2],
                        "confidence": r[3],
                        "sources": ", ".join(json.loads(r[4])),
                        "matched": bool(r[5]),
                    }
                    for r in rows
                ]
            ),
            use_container_width=True,
        )
    else:
        st.info("No queries logged yet. Run one in the 'Try a query' tab.")

# ---------------------------------------------------------------------------
# Reminders
# ---------------------------------------------------------------------------
with tab_reminders:
    st.subheader("Add a reminder")
    r_user = st.text_input("User ID ", value="demo-user-1")
    r_scheme = st.text_input("Scheme name")
    r_date = st.date_input("Due date")
    if st.button("Add reminder"):
        agent.add_reminder(r_user, r_scheme, str(r_date))
        st.success("Reminder added.")

    st.subheader("Due reminders")
    due = agent.due_reminders()
    if due:
        st.table([{"id": d[0], "user": d[1], "scheme": d[2], "due": d[3]} for d in due])
    else:
        st.info("Nothing due today.")

# ---------------------------------------------------------------------------
# Re-match preview
# ---------------------------------------------------------------------------
with tab_rematch:
    st.subheader("Proactive re-matching preview")
    st.caption(
        "Demonstrates the 'Setu remembers what you've already accessed and "
        "flags you for the next scheme' claim - compares what's indexed "
        "against what this user has already been matched to."
    )
    rm_user = st.text_input("User ID to check", value="demo-user-1", key="rematch_user")
    if st.button("Check for unclaimed schemes"):
        profile = agent.get_profile(rm_user)
        try:
            indexed = rag.list_indexed_sources()
        except Exception as e:
            indexed = []
            st.warning(f"Could not read Chroma collection: {e}")
        unclaimed = sorted(set(indexed) - set(profile))

        st.markdown(f"**Already matched:** {', '.join(profile) or 'none yet'}")
        if unclaimed:
            st.success(
                f"{len(unclaimed)} indexed scheme(s) this user hasn't been matched to yet: "
                f"{', '.join(unclaimed)}"
            )
            st.caption(
                "In production this is what triggers the proactive nudge - "
                "this view is just making that logic visible, not sending anything."
            )
        else:
            st.info("Nothing unclaimed - either fully covered or no queries run yet.")
