"""FR-002.9 wiring: a tier-1a run through the live started replay records exactly the requests the
scripted path sent, in order, with their bodies; dropping one app's listener turns the goal red."""

from __future__ import annotations

import json
from pathlib import Path

from miassist_eval import replay, suite
from miassist_eval.canonical import sha256
from tests.support import suites


async def test_the_effects_log_holds_exactly_the_scripted_requests(tmp_path: Path) -> None:
    result = await suites.suite(tmp_path).run()
    run_dir = result.out_dir / result.records[0]["run_id"]
    effects = [json.loads(x) for x in (run_dir / "effects.jsonl").read_text().splitlines()]
    sent = [
        (s.arguments["method"], s.arguments["path"], sha256(s.arguments.get("body")))
        for s in suites.DATASET_STEPS
    ]
    assert [(e["method"], e["path"], e["request_body_sha256"]) for e in effects] == sent


async def test_dropping_one_apps_listener_turns_the_goal_red(tmp_path: Path, monkeypatch) -> None:
    real = replay.Replay.app_for

    def without_midataworks(self, app):
        if app == "midataworks":
            from starlette.applications import Starlette

            return Starlette()  # a listener that serves nothing
        return real(self, app)

    monkeypatch.setattr(replay.Replay, "app_for", without_midataworks)
    result = await suites.suite(tmp_path).run()
    assert result.records and all(r["outcome"] != "success" for r in result.records)
    assert suite.MAX_ATTEMPTS >= 1
