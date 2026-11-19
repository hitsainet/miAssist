"""``verdict.facts`` and ``render`` (FPRD FR-003.17, FR-003.18, §4.2; FTASKS 5.2 - 5.4)."""

from __future__ import annotations

import re
from typing import Any

import pytest

from miassist.guidance.loader import MARKER, Guidance
from miassist.playbooks._shared.calm import words
from miassist.playbooks.detector_probe import verdict

G = Guidance()
OVERCLAIM = (
    "causal",
    "causes",
    "proves",
    "guarantees",
    "reliable",
    "ready to serve",
    "production-ready",
)


def say(key: str, **slots: Any) -> str:
    return words(G, "detector-probe", key, **slots)


def report(rung: int, *, ood: bool = True, counted: bool = True) -> dict[str, Any]:
    return {
        "probe": {"rung": rung},
        "catch_rate": (
            {"sets": [{"name": "s-ood", "positives": 410, "caught": 41, "needed": 205}]}
            if ood
            else None
        ),
        "everyday_text": {
            "sets": [
                {
                    "name": "s-every",
                    "rows": 1200,
                    "false_alarms": 4,
                    "allowed": 24,
                    "counts": counted,
                    "note": "1,200 rows, fewer than the check needs",
                }
            ]
        },
        "nonsense_text": {
            "sets": [
                {"name": "s-non", "rows": 2000, "false_alarms": 1, "allowed": 40, "counts": True}
            ]
        },
        "evaluations": [
            {"metrics": {"scored": True, "ci": {"low": 0.62}}},
            {"metrics": {"scored": False, "ci": {"low": 0.1}}},
            {"metrics": {"scored": True, "ci": {"low": 0.55}}},
        ],
    }


@pytest.mark.parametrize("rung", [0, 1, 2, 3])
def test_numbers_per_rung(rung: int) -> None:
    f = verdict.facts(report(rung))
    assert f.rung == rung
    assert f.ood_sets == [
        {"name": "s-ood", "caught": 41, "positives": 410, "rate": 10, "needed": 205}
    ]
    assert f.everyday_sets[0]["per_1000"] == 3.3 and f.everyday_sets[0]["allowed_per_1000"] == 20.0
    assert f.nonsense_sets[0]["per_1000"] == 0.5
    assert f.auroc_ci_low == 0.55, "the unscored set's interval is ignored"
    text = verdict.render(f, say)
    assert f"rung {rung}" in text and "10% of positives" in text and "41 of 410" in text
    assert "3.3 false alarms per 1,000" in text and "up to 20.0" in text
    assert say(f"verdict.next.r{rung}") in text


def test_a_set_that_does_not_count_is_shown_with_its_note() -> None:
    f = verdict.facts(report(1, counted=False))
    assert f.everyday_sets == [] and f.not_counted == ["1,200 rows, fewer than the check needs"]
    assert "fewer than the check needs" in verdict.render(f, say)


def test_caveat_when_the_bar_shares_the_test_split() -> None:
    assert say("verdict.caveat") in verdict.render(verdict.facts(report(2), shared_split=True), say)
    assert say("verdict.caveat") not in verdict.render(verdict.facts(report(2)), say)


def all_renderings() -> list[tuple[int, str]]:
    out = []
    for rung in (0, 1, 2, 3):
        for ood in (True, False):
            for shared in (True, False):
                f = verdict.facts(report(rung, ood=ood), shared_split=shared)
                out.append((rung, verdict.render(f, say)))
                out.append((rung, verdict.expert_line(f, say)))
    return out


def test_no_overclaim_below_rung_two_and_never_causal() -> None:
    for rung, text in all_renderings():
        low = text.lower()
        assert "causal" not in low
        if rung < 2:
            assert not [w for w in OVERCLAIM if w in low], (rung, text)


def test_overclaim_words_appear_only_in_the_ready_template() -> None:
    """Every template in the words file is scanned: only verdict.ready may say 'ready to serve'."""
    texts = G.playbooks["detector-probe"].texts
    for key, text in texts.items():
        low = text.lower()
        if key == "verdict.ready":
            assert "ready to serve" in low and "causal" not in low
            continue
        assert not [w for w in OVERCLAIM if re.search(rf"\b{re.escape(w)}\b", low)], key


def test_every_glossary_marker_has_an_entry() -> None:
    texts = G.playbooks["detector-probe"].texts
    for key, text in texts.items():
        for term in MARKER.findall(text):
            assert term in G.glossary, (key, term)
    for term in (
        "behaviour-key",
        "positive-meaning",
        "view",
        "everyday-text",
        "nonsense-text",
        "out-of-distribution",
        "pooling-rule",
        "rung",
        "auroc",
        "catch-rate",
        "false-alarm",
        "shipped-bar",
        "parity",
        "armed",
    ):
        assert term in G.glossary, term


def test_dropping_the_everyday_line_is_seen() -> None:
    text = verdict.render(verdict.facts(report(2)), say)
    assert "everyday text" in text.lower()
