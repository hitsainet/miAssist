"""The fluency rule at its boundary (005 FPRD FR-005.13; FTDD I4).

ENH-012 acceptance, round 1 (review/enh012-acceptance, 2026-11-26): control E5-S01 moved the collapse
threshold from 0.4 to 0.3 and the whole suite stayed green. The fixtures were far from the line
(TTR 0.1 and 1.0), so the rule the verdict states ("text with fewer than 4 distinct words in 10 is
treated as fallen apart") was never checked where it decides. These cases sit on it.
"""

from __future__ import annotations

import pytest

from miassist.guidance.loader import Guidance
from miassist.playbooks.steering import fluency

THREE_IN_TEN = "rain rain rain cloud cloud cloud wind wind wind wind"  # TTR 0.3
FOUR_IN_TEN = "rain cloud wind sun rain cloud wind sun rain cloud"  # TTR 0.4
FOUR_WORDS = "rain cloud wind sun"  # fewer than MIN_TOKENS words, all distinct


@pytest.mark.parametrize(
    "text,collapsed",
    [(THREE_IN_TEN, True), (FOUR_IN_TEN, False), (FOUR_WORDS, True)],
    ids=["three-distinct-in-ten", "four-distinct-in-ten", "four-words"],
)
def test_the_rule_at_its_boundary(text: str, collapsed: bool) -> None:
    assert fluency.collapsed(text) is collapsed


def test_a_reply_below_the_line_ends_the_usable_range() -> None:
    verdict = fluency.verdict(FOUR_IN_TEN, [(1.0, FOUR_IN_TEN), (2.0, THREE_IN_TEN)])
    assert (verdict.usable, verdict.first_collapse) == (1.0, 2.0)


def test_the_stated_rule_is_the_rule_applied() -> None:
    """The verdict quotes the rule in words; the numbers it applies are those words."""
    assert fluency.COLLAPSE_BELOW == 0.4 and fluency.MIN_TOKENS == 5
    text = Guidance().playbooks["steering"].texts["verdict.rule"]
    assert "fewer than 4 distinct words in 10" in text and "TTR below 0.4" in text
