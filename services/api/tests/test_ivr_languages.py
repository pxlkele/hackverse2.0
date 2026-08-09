"""
Every offered language must be able to hold a whole call.

Three things have to line up for that, and they used to live in three places
that drifted apart: the language had to be accepted by begin(), it had to have a
prompt set, and it had to have cached audio. The PWA hardcoded two languages
while VOICES advertised eight, so picking Bengali in one place got you English
prompts read in a Bengali voice.

The last test here is the important one. edge-tts synthesises over the network,
so a prompt with no cached mp3 is *silent* with the wifi off — and the demo is
run wifi-off deliberately. If you edit a prompt string, this test fails until
you re-run precache_prompts(), which is exactly the reminder you want.
"""

from __future__ import annotations

import pytest

from channels import ivr_sim
from services.api.core import voice

LANGS = ivr_sim.SUPPORTED_LANGUAGES


def test_the_eight_languages_are_the_ones_we_can_hear():
    """
    A language we cannot transcribe cannot hold a voice call. SUPPORTED_LANGUAGES
    must therefore be a subset of what ASR actually manages — measured, not
    claimed.
    """
    assert set(LANGS) <= voice.ASR_LANGUAGES


@pytest.mark.parametrize("lang", LANGS)
def test_every_language_has_a_voice_and_a_label(lang):
    assert lang in voice.VOICES
    assert ivr_sim.LANGUAGE_LABELS.get(lang)


@pytest.mark.parametrize("lang", LANGS)
@pytest.mark.parametrize("key", sorted(ivr_sim.PROMPTS))
def test_every_prompt_exists_in_every_language(key, lang):
    """
    The greeting is the one deliberate exception: it is the spoken language menu,
    played before the caller has chosen, so it stays a Hindi/English pair.
    """
    if key == "greeting":
        pytest.skip("the greeting is the pre-selection language menu")
    assert lang in ivr_sim.PROMPTS[key], f"{key} has no {lang}"


@pytest.mark.parametrize("lang", LANGS)
def test_a_call_begins_in_the_language_asked_for(lang):
    call_id, turn = ivr_sim.begin(lang)
    assert ivr_sim._session(call_id).language == lang
    # Straight to the question — a client that names its language never hears
    # the menu.
    assert turn.state == "ask_situation"
    assert turn.say == ivr_sim.prompt_text("ask_situation", lang)


def test_an_unknown_language_falls_back_to_the_menu_rather_than_crashing():
    _call_id, turn = ivr_sim.begin("xx")
    assert turn.state == "greeting"


def test_prompt_text_falls_back_instead_of_raising():
    """PROMPTS[key][lang] would KeyError, and a KeyError here is a dead call."""
    assert ivr_sim.prompt_text("thinking", "xx") == ivr_sim.PROMPTS["thinking"]["hi"]


def test_every_prompt_has_cached_audio_so_the_demo_speaks_offline():
    missing = ivr_sim.missing_prompt_audio()
    assert not missing, (
        f"{len(missing)} prompt(s) have no cached mp3 and would be SILENT with "
        f"the wifi off: {missing}. Run channels.ivr_sim.precache_prompts()."
    )
