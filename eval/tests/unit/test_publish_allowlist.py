"""FR-002.47 (M14): the published file carries allow-listed figures only."""

from __future__ import annotations

import json

from miassist_eval import report


def test_transcripts_and_app_answers_never_publish() -> None:
    summary = {
        "schema": "miassist.eval-report/v1",
        "label": "r1",
        "generated_utc": "t",
        "headings": [],
        "verdict": "BAR MET",
        "reasons": ["x"],
        "suites": ["s"],
        "rejected": [{"run_id": "r", "reason": "y"}],
        "comparisons": [],
        "manual": {},
        "cells": [
            {
                "key": ["detector-probe", "claude_code", "miassist", "1b"],
                "attempts": 10,
                "valid": 10,
                "successes": 9,
                "bar_calls": {"median": 9},
                "stuck": {},
                "verdicts": {"success": "PASS"},
                "baseline_basis": "baseline_runs",
                "versions": [],
                "transcript_excerpt": "Customer Jane wants a refund",
                "app_answer": {"name": "operator-dataset"},
            }
        ],
    }
    published = report.publish(summary)
    text = json.dumps(published)
    assert "Customer Jane" not in text and "operator-dataset" not in text
    allowed_top = set(report.PUBLISH_FIELDS["top"]) | {"cells"}
    assert set(published) <= allowed_top
    for cell in published["cells"]:
        assert set(cell) <= set(report.PUBLISH_FIELDS["cell"])


def test_the_allow_list_holds_no_free_text_field() -> None:
    banned = {
        "transcript",
        "transcript_excerpt",
        "app_answer",
        "answer",
        "rejected",
        "reasons",
        "manual",
        "comparisons",
        "suites",
    }
    assert not banned & (set(report.PUBLISH_FIELDS["top"]) | set(report.PUBLISH_FIELDS["cell"]))
