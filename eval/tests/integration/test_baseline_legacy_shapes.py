"""C-10: the baseline surface is measured with today's legacy shapes; no next_steps is required."""

from __future__ import annotations

from miassist_eval import shapes

LEGACY = [
    {"next": "call get_task_status", "approval_request_id": "x", "status": "pending_approval"},
    {"approval_id": "a1", "status": "pending", "decide_in": "midataworks"},
    {"unavailable": "miserver", "reason": "down"},
]


def test_legacy_results_pass_on_the_baseline() -> None:
    for result in LEGACY:
        assert shapes.check("baseline", result, False, "text") == []


def test_legacy_errors_pass_on_the_baseline() -> None:
    assert shapes.check("baseline", None, True, "Error: Something went wrong") == []


def test_the_same_error_fails_on_the_miassist_surface() -> None:
    assert shapes.check("miassist", None, True, "Error: Something went wrong")
