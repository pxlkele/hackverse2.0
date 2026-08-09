"""
The narration must never misstate money.

narrate.py's job is translation, not arithmetic: the rule engine decides the
amounts and they are interpolated into the facts before the model ever sees
them. The prompt tells it "Never change a number".

It changes them anyway. Measured, asked for Marathi, granite4:tiny-h rendered
PMSBY's ₹2,00,000 as २०००००० — twenty lakh, a tenfold overstatement, twice in
one answer. Telling a street vendor the government owes him ₹20,00,000 is the
worst sentence this product could produce, and no amount of prompt wording makes
it impossible. So it is verified instead.

These tests are cheap and involve no model. They protect every language at once,
including the two the demo actually runs in.
"""

from __future__ import annotations

import pytest

from services.api.core import narrate

# The real facts one decision produced, as narrate_all builds them.
FACTS = ["For PMSBY you can get up to 200000 rupees. You are 1 steps away - free, about 2 days."]


def test_the_measured_marathi_failure_is_caught():
    """The actual line that came back from the model, not a constructed one."""
    bad = "आता पीएमएसबीवायसाठी तुम्ही अधिकतम २०००००० रुपये मिळवू शकता."
    assert narrate._misstated_money(bad, FACTS) == {2000000}


@pytest.mark.parametrize(
    "spoken",
    [
        "आता पीएमएसबीवायसाठी तुम्ही अधिकतम २००००० रुपये मिळवू शकता.",   # Devanagari digits
        "PMSBY இல் உங்களுக்கு 200000 ரூபாய் வரை கிடைக்கும்",              # Tamil, ASCII digits
        "PMSBY থেকে আপনি 200000 টাকা পেতে পারেন",                        # Bengali
        "For PMSBY you can get up to 200000 rupees.",                     # English
    ],
)
def test_the_correct_amount_passes_in_any_script(spoken):
    assert not narrate._misstated_money(spoken, FACTS)


def test_step_counts_and_day_estimates_are_not_policed():
    """
    Below ₹100 we do not police wording — "about two days" is a legitimate
    rendering of 2, and rejecting it would send every answer to the English
    fallback. Money is the only thing that must survive exactly.
    """
    assert not narrate._misstated_money("तुम्ही ३ पायरी दूर आहात, ५ दिवस", FACTS)


def test_indic_digits_are_compared_on_the_same_footing():
    """A wrong amount written in Tamil numerals must fail exactly like ASCII."""
    assert narrate._amounts_in("௨௦௦௦௦௦௦") == {2000000}
    assert narrate._amounts_in("२०००००० and 200000") == {2000000, 200000}
