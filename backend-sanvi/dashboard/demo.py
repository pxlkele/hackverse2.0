"""
Setu - live demo screen (judge-facing).

This is the ONLY screen you show judges. Deliberately minimal: record,
Setu answers, Setu speaks back. No query logs, no confidence tables, no
internal plumbing - that's what dashboard/app.py is for.

Run:
    streamlit run dashboard/demo.py
"""
import os
import sys
import streamlit as st

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))
from backend import agent, voice

st.set_page_config(page_title="Setu", layout="centered")
st.title("Setu")
st.caption("Speak your situation. Setu finds what you're eligible for.")

language = st.selectbox("Reply language", list(voice.TTS_VOICES.keys()), index=0)

audio = st.audio_input("Speak here")

if audio is not None:
    with st.spinner("Listening..."):
        transcript = voice.transcribe(audio.read())

    if not transcript:
        st.warning("Didn't catch that - try again, a bit closer to the mic.")
    else:
        st.markdown(f"**You said:** {transcript}")

        with st.spinner("Checking what you're eligible for..."):
            result = agent.process_query("live-demo-user", transcript)

        st.markdown("**Setu:**")
        st.write(result["answer"])

        with st.spinner("Speaking..."):
            spoken_text = voice.spoken_portion(result["answer"])
            audio_bytes = voice.synthesize(spoken_text, language)
        st.audio(audio_bytes, format="audio/mp3")
