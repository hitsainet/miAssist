"""FR-002.5, FR-002.12, FR-002.13: lint, integrity and staleness are called on the live start path,
in that order, once each; a refusal records zero runs; a hinted goal records zero runs."""

from __future__ import annotations

import copy
import json
from pathlib import Path

from miassist_eval import cassette, classes, goals, lint, staleness
from tests.support import suites


def spy(monkeypatch, module, name: str, calls: list[str]) -> None:
    real = getattr(module, name)

    def wrapped(*a, **kw):
        calls.append(f"{module.__name__.rsplit('.', 1)[1]}.{name}")
        return real(*a, **kw)

    monkeypatch.setattr(module, name, wrapped)


async def test_a_clean_suite_succeeds_and_calls_each_check_once_in_order(
    tmp_path: Path, monkeypatch
) -> None:
    calls: list[str] = []
    spy(monkeypatch, lint, "lint", calls)
    spy(monkeypatch, cassette, "load", calls)
    spy(monkeypatch, staleness, "check_cassette", calls)
    result = await suites.suite(tmp_path).run()
    assert result.refused is None
    assert calls == ["lint.lint", "cassette.load", "staleness.check_cassette"]
    assert [r["outcome"] for r in result.records] == ["success"], result.records[0]["cls"]
    rec = result.records[0]
    assert [m["id"] for m in rec["milestones_reached"]] == ["version_built", "checked", "published"]
    assert rec["calls"]["total"] == 3


async def test_a_hinted_goal_records_zero_runs(tmp_path: Path) -> None:
    raw = copy.deepcopy(goals.load().raw)
    raw["goals"][1]["phrasings"]["a"] += " Use call_app for it."
    s = suites.suite(tmp_path, goal_set=goals.GoalSet(raw))
    result = await s.run()
    assert result.refused is not None and result.refused.cls == classes.LINT_REFUSED
    assert "call_app" in result.refused.detail
    assert result.records == []
    assert list(s.out_dir.glob("r-*")) == []
    assert json.loads((s.out_dir / "suite.json").read_text())["attempts"] == []


async def test_a_doctored_take_records_zero_runs(tmp_path: Path) -> None:
    s = suites.suite(tmp_path)
    path = s.plan.takes["dataset-refund"] / "cassette.json"
    path.write_text(path.read_text().replace("evalfx-refund-messages", "evalfx-refund-messageZ"))
    result = await s.run()
    assert result.refused is not None and result.refused.cls == classes.CASSETTE_INTEGRITY
    assert result.records == [] and list(s.out_dir.glob("r-*")) == []


async def test_a_stale_take_records_zero_runs(tmp_path: Path) -> None:
    records = suites.dataset_records()
    records[0]["answer"]["body"] = {**suites.VERSION, "total_rows": "fifty"}
    s = suites.suite(tmp_path, records=records)
    result = await s.run()
    assert result.refused is not None and result.refused.cls == classes.CASSETTE_STALE
    assert "total_rows" in result.refused.detail and result.records == []


async def test_reference_age_fail_mode_records_zero_runs(tmp_path: Path, monkeypatch) -> None:
    from datetime import UTC, datetime, timedelta

    monkeypatch.setenv("MIASSIST_EVAL_REF_AGE_MODE", "fail")
    s = suites.suite(tmp_path)
    s.now = lambda: datetime.now(UTC) + timedelta(days=31)
    result = await s.run()
    assert result.refused is not None and result.refused.cls == classes.REFERENCE_TOO_OLD
    assert result.records == []


async def test_reference_age_warn_mode_runs_and_marks_every_record(
    tmp_path: Path, monkeypatch
) -> None:
    from datetime import UTC, datetime, timedelta

    monkeypatch.delenv("MIASSIST_EVAL_REF_AGE_MODE", raising=False)
    said: list[str] = []
    s = suites.suite(tmp_path, said=said)
    s.now = lambda: datetime.now(UTC) + timedelta(days=31)
    result = await s.run()
    assert result.refused is None and result.records
    assert all(r["reference_stale"] is True for r in result.records)
    assert any(line.startswith("WARNING reference_too_old") for line in said)


async def test_reference_ages_are_printed_first(tmp_path: Path) -> None:
    said: list[str] = []
    await suites.suite(tmp_path, said=said).run()
    assert said[0].startswith("reference ") and "days old" in said[0]


async def test_a_result_shape_failure_on_the_miassist_surface_fails_the_run(tmp_path: Path) -> None:
    """FR-002.16: an error whose line 1 is not a lower-case error_code fails tier 1a (A30)."""
    from miassist_eval.drivers.scripted import Step

    steps = [
        *suites.DATASET_STEPS,
        Step("call_app", {"app": "nope", "method": "GET", "path": "/x"}),
    ]
    result = await suites.suite(tmp_path, steps=steps).run()
    assert result.records[0]["outcome"] == "failed"
    assert result.records[0]["cls"] == classes.RESULT_SHAPE


async def test_a_goal_with_an_unguarded_gpu_start_records_zero_runs(
    tmp_path: Path, vectors_without_steering: Path
) -> None:
    """R1 review fix (OR1-002-4), 2026-11-16: the steering goal on the miAssist surface refuses at
    suite start with ``gpu_list_incomplete`` while the vectors lack its GPU starts; zero runs.
    Integration (OVN-miassist-int-5): pinned against vectors without the steering rows."""
    s = suites.suite(tmp_path / "out", goal_id="tone-warmer")
    result = await s.run()
    assert result.refused is not None and result.refused.cls == classes.GPU_LIST_INCOMPLETE
    assert result.records == [] and list(s.out_dir.glob("r-*")) == []


async def test_the_steering_goal_starts_once_the_vectors_hold_its_gpu_starts(
    tmp_path: Path,
) -> None:
    """Integration (OVN-miassist-int-5): with Core's vendored vectors the steering goal is no longer
    refused at suite start for its GPU list."""
    result = await suites.suite(tmp_path, goal_id="tone-warmer").run()
    assert result.refused is None or result.refused.cls != classes.GPU_LIST_INCOMPLETE
