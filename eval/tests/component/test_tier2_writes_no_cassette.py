"""R2M-7, A37: a tier-2 run through the recorder writes no take and nothing under the cassette
root; a ``record`` run writes one."""

from __future__ import annotations

from pathlib import Path

import pytest

from miassist_eval import allowed, cassette, classes
from miassist_eval.classes import Refusal
from miassist_eval.recorder import Recorder
from tests.support import harness

H = harness.HEADERS["midataworks"]


async def forward(app, method, path, query, headers, body):
    return 200, {}, {"id": "evalfx-ds-1"}


async def run(writing: bool) -> Recorder:
    rec = Recorder(
        edge=harness.edge(),
        forward=forward,
        allowed_set=allowed.AllowedSet(),
        app_versions={"midataworks": "t"},
        writing=writing,
    )
    await rec.handle("midataworks", "GET", "/api/v1/datasets/evalfx-ds-1", {}, H, None)
    return rec


def files_under(root: Path) -> list[Path]:
    return [p for p in root.rglob("*") if p.is_file()] if root.exists() else []


async def test_tier2_holds_no_record_and_refuses_to_build_a_take(tmp_path: Path) -> None:
    rec = await run(writing=False)
    assert rec.records == []
    assert len(rec.effects.lines) == 1, "the effects log still records the run"
    with pytest.raises(Refusal) as caught:
        rec.cassette("t")
    assert caught.value.cls == classes.HARNESS_ERROR
    assert files_under(tmp_path) == []


async def test_a_record_run_writes_one_take(tmp_path: Path) -> None:
    rec = await run(writing=True)
    doc = rec.cassette("t")
    manifest = {
        "cassette_id": "c1",
        "goal_id": "g",
        "surface": "baseline",
        "take": "t1",
        "recording_run_id": "run-1",
        "recorder_version": "0.1.0",
        "started_utc": "a",
        "ended_utc": "b",
        "apps": {"midataworks": {"base_path": "", "openapi_sha256": "x", "version": "t"}},
        "fairness": harness.fairness_block(),
        "allowed_ids": sorted(rec.allowed_set.created),
    }
    cassette.write_take(tmp_path / "g/baseline/t1", doc, manifest, {"run_id": "run-1"}, {}, {})
    assert (tmp_path / "g/baseline/t1/cassette.json").is_file()
