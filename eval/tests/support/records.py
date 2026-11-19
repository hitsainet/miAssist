"""Run-record fixtures for report tests (FR-002.30-FR-002.39)."""

from __future__ import annotations

from typing import Any

SHA = "a" * 64


def rec(
    i: int,
    outcome: str = "success",
    cls: str | None = None,
    *,
    goal: str = "detector-refund",
    client: str = "claude_code",
    surface: str = "miassist",
    tier: str = "1b",
    bar_calls: int = 10,
    first_useful: float | None = 300.0,
    model: str = "m-1",
    goal_sha: str = SHA,
) -> dict[str, Any]:
    return {
        "schema": "miassist.eval-run/v1",
        "run_id": f"r-{i:03d}",
        "suite_id": "s",
        "attempt": 1,
        "attempt_order": i,
        "surface": surface,
        "tier": tier,
        "client": {"name": client, "version": "1"},
        "model": {"requested": model, "served": model, "mismatch": False},
        "server_under_test": {"kind": surface},
        "apps": {"miworkbench": {"version": "1", "openapi_sha256": "x", "drift": "none"}},
        "harness_version": "0.1.0",
        "cassette": None,
        "goal": {"id": goal, "phrasing": "a", "goal_set_sha256": goal_sha},
        "outcome": outcome,
        "cls": cls,
        "milestones_reached": [],
        "stuck_at": None,
        "calls": {
            "total": bar_calls,
            "bar_calls": bar_calls,
            "polls": 0,
            "errors": 0,
            "by_tool": {},
        },
        "tool_choice": {},
        "tokens": {
            "input": 1,
            "output": 1,
            "cache_read": None,
            "cache_write": None,
            "reported": {"input": True, "output": True},
        },
        "time": {"first_useful_active_s": first_useful, "active_s": 400.0},
        "user_nudges": 0,
        "reference_stale": False,
        "artifacts": {},
    }


PLAYBOOK_OF = {
    "detector-refund": "detector-probe",
    "dataset-refund": "dataset",
    "tone-warmer": "steering",
}
