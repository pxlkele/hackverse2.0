"""
An answer must be traceable to something the caller actually said.

Given a profile with every field empty, the rule engine still returns PMSBY,
PMJJBY and PM SVANidhi as eligible, with real rupee figures attached - none of
those schemes has a requirement an empty profile fails. That is correct
behaviour for the engine and a disaster at the microphone: it is exactly what a
failed transcription produces, and the caller is then told a confident number
derived from nothing they said.

This is not hypothetical. Bengali speech transcribes as romanised Latin
("Ami kul kathai shabjibikri kuri"), from which age, income and category all
come back None, and the phone showed three schemes and a rupee amount anyway.
"""

from __future__ import annotations

from channels.ivr_sim import _has_usable_facts
from services.api.core.schemas import Profile


class TestHasUsableFacts:
    def test_an_empty_profile_has_nothing_to_answer_from(self):
        assert not _has_usable_facts(Profile(raw_text="", language="bn"))

    def test_the_real_bengali_failure(self):
        """What extraction actually returned for the Bengali clip."""
        profile = Profile(
            raw_text="Ami kul kathai shabjibikri kuri, amar boyosh butrish.",
            language="bn",
            occupation="informal worker",   # the generic guess, not a real fact
        )
        assert not _has_usable_facts(profile)

    def test_age_alone_is_enough(self):
        assert _has_usable_facts(Profile(raw_text="x", language="hi", age=32))

    def test_category_alone_is_enough(self):
        """
        Gujarati lost age and income but did get the category. That caller
        still deserves what being a street vendor alone qualifies them for.
        """
        profile = Profile(raw_text="x", language="gu", occupation_category="street_vendor")
        assert _has_usable_facts(profile)

    def test_either_income_field_counts(self):
        assert _has_usable_facts(Profile(raw_text="x", language="ta", daily_income=800))
        assert _has_usable_facts(Profile(raw_text="x", language="hi", monthly_income=24000))

    def test_a_full_profile_passes(self):
        profile = Profile(
            raw_text="x", language="hi", age=32,
            occupation_category="street_vendor", daily_income=800,
        )
        assert _has_usable_facts(profile)
