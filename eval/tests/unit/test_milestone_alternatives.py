"""FR-002.7 (R1M-21): the steering ``exported`` milestone is reached through either route, driven
through replay by the scripted path."""

from __future__ import annotations

from pathlib import Path

from miassist_eval import goals
from miassist_eval.drivers.scripted import Step
from tests.support import harness, suites

EXPORT = {"profile": {"id": "evalfx-cp"}, "members": []}


async def test_exported_reached_through_the_get_export_route(tmp_path: Path) -> None:
    records = [
        harness.record(
            0,
            "miworkbench",
            "GET",
            "/api/v1/cluster-profiles/evalfx-cp/export",
            "/api/v1/cluster-profiles/{profile_id}/export",
            200,
            EXPORT,
        )
    ]
    steps = [
        Step(
            "call_app",
            {
                "app": "miworkbench",
                "method": "GET",
                "path": "/api/v1/cluster-profiles/evalfx-cp/export",
            },
        )
    ]
    s = suites.suite(tmp_path, records=records, steps=steps, goal_id="tone-warmer")
    # The baseline surface: on the miAssist surface the steering goal is refused at suite start
    # until Core re-vendors the steering rows (R1 review fix OR1-002-4); milestones are the same.
    s.plan.surface = "baseline"
    result = await s.run()
    assert result.refused is None
    reached = [m["id"] for m in result.records[0]["milestones_reached"]]
    assert reached == ["exported"]


def test_both_alternatives_are_declared() -> None:
    m = next(m for m in goals.load().goal("tone-warmer")["milestones"] if m["id"] == "exported")
    assert {(a["method"], a["route"]) for a in m["any_of"]} == {
        ("POST", "/api/v1/cluster-profiles/export-bundle"),
        ("GET", "/api/v1/cluster-profiles/{profile_id}/export"),
    }
