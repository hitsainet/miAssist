"""FR-002.21, FR-002.25, FR-002.27, FR-002.29: classes, precedence, artifacts, required versions."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from miassist_eval import classes, goals, schemas, score
from miassist_eval.canonical import sha256_file
from tests.support import harness

REQ = ["data_ready", "trained"]


@pytest.mark.parametrize("cause", sorted(classes.INVALID_CAUSES))
def test_each_infrastructure_cause_is_invalid(cause: str) -> None:
    assert score.outcome(cause, [], [], REQ, None, []) == ("invalid", cause)


def test_a_cassette_miss_is_a_failure_never_invalid() -> None:
    assert score.outcome(None, [("off_recording", "x")], REQ, REQ, None, []) == (
        "failed",
        "off_recording",
    )


def test_precedence_decision_over_unknown_route_over_header_over_miss() -> None:
    f = [
        ("off_recording", "a"),
        ("missing_agent_header", "b"),
        ("unknown_route", "c"),
        ("agent_attempted_decision", "d"),
    ]
    assert score.outcome(None, f, REQ, REQ, None, [])[1] == "agent_attempted_decision"
    assert score.outcome(None, f[:3], REQ, REQ, None, [])[1] == "unknown_route"
    assert score.outcome(None, f[:2], REQ, REQ, None, [])[1] == "missing_agent_header"


def test_milestone_shortfall_reads_the_tap_for_a_loop() -> None:
    tap = [{"method": "tools/call", "tool": "t", "args_sha256": "h", "is_error": True}] * 3
    assert score.outcome(None, [], ["data_ready"], REQ, None, tap) == ("failed", "wrong_tool_loop")
    assert score.outcome(None, [], ["data_ready"], REQ, None, tap[:1])[1] == "argument_refusal"
    assert score.outcome(None, [], ["data_ready"], REQ, None, [])[1] == "asked_and_stopped"


def test_final_message_failure_after_milestones() -> None:
    assert score.outcome(None, [], REQ, REQ, "unsupported_figure", []) == (
        "failed",
        "unsupported_figure",
    )
    assert score.outcome(None, [], REQ, REQ, None, []) == ("success", None)


def make_run(tmp_path: Path) -> tuple[dict, Path]:
    files = {
        "transcript": "transcript.json",
        "tap_log": "tap.jsonl",
        "effects_log": "effects.jsonl",
        "clock": "clock.json",
    }
    (tmp_path / "transcript.json").write_text("{}")
    (tmp_path / "tap.jsonl").write_text(
        json.dumps({"method": "tools/call", "tool": "x", "t_mono": 1, "t_answer": 2}) + "\n"
    )
    eff = [
        {
            "t_mono": 1.5,
            "app": "miworkbench",
            "method": "POST",
            "route": "/api/v1/probe-monitors/datasets",
            "path": "/api/v1/probe-monitors/datasets",
            "status": 201,
            "answer": {},
        }
    ]
    (tmp_path / "effects.jsonl").write_text("".join(json.dumps(e) + "\n" for e in eff))
    (tmp_path / "clock.json").write_text("{}")
    meta = {
        "schema": "miassist.eval-run/v1",
        "run_id": "r1",
        "suite_id": "s",
        "attempt": 1,
        "surface": "miassist",
        "tier": "1a",
        "client": {"name": "scripted", "version": "2.3.0"},
        "model": {"requested": None, "served": None, "mismatch": False},
        "server_under_test": {"kind": "miassist"},
        "apps": {"miworkbench": {"version": "1", "openapi_sha256": "x", "drift": "none"}},
        "harness_version": "0.1.0",
        "cassette": None,
        "goal": {"id": "detector-refund", "phrasing": "a", "goal_set_sha256": "a" * 64},
        "tokens": {
            "input": None,
            "output": None,
            "cache_read": None,
            "cache_write": None,
            "reported": {
                "input": False,
                "output": False,
                "cache_read": False,
                "cache_write": False,
            },
        },
        "user_nudges": 0,
        "reference_stale": False,
        "artifacts": {
            k: {"path": v, "sha256": sha256_file(tmp_path / v)} for k, v in files.items()
        },
        "time": {"start": 0, "end": 10},
        "failures": [],
    }
    return meta, tmp_path


def test_a_record_carries_every_field(tmp_path: Path) -> None:
    meta, run_dir = make_run(tmp_path)
    record = score.build_record(
        meta, run_dir, goals.load().goal("detector-refund"), harness.profiles()
    )
    assert record["milestones_reached"] == [{"id": "data_ready", "t": 1.5}]
    assert record["outcome"] == "failed" and record["calls"]["total"] == 1
    assert score.verify_artifacts(record, run_dir) is None


@pytest.mark.parametrize(
    "field", ["client", "model", "apps", "harness_version", "goal", "cassette"]
)
def test_a_missing_version_field_fails_validation(tmp_path: Path, field: str) -> None:
    meta, run_dir = make_run(tmp_path)
    record = score.build_record(
        meta, run_dir, goals.load().goal("detector-refund"), harness.profiles()
    )
    del record[field]
    assert schemas.errors("eval-run", record)


def test_a_zero_token_figure_the_client_did_not_report_fails(tmp_path: Path) -> None:
    meta, run_dir = make_run(tmp_path)
    record = score.build_record(
        meta, run_dir, goals.load().goal("detector-refund"), harness.profiles()
    )
    record["tokens"]["input"] = 0
    assert schemas.errors("eval-run", record)
    record["tokens"]["reported"]["input"] = True
    assert schemas.errors("eval-run", record) == []


def test_a_missing_or_altered_artifact_rejects_the_record(tmp_path: Path) -> None:
    meta, run_dir = make_run(tmp_path)
    record = score.build_record(
        meta, run_dir, goals.load().goal("detector-refund"), harness.profiles()
    )
    (run_dir / "tap.jsonl").write_text("changed\n")
    assert "altered" in score.verify_artifacts(record, run_dir)
    (run_dir / "transcript.json").unlink()
    assert "missing" in score.verify_artifacts(record, run_dir)
