"""FTDD §5.1 exit codes; ``bar confirm`` needs --yes and a baseline; ``manual new`` writes every
item not_run; ``publish`` writes figures only."""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from miassist_eval import cli


def test_bar_confirm_without_a_baseline_refuses(tmp_path: Path) -> None:
    assert cli.main(["bar", "confirm", "--baseline", str(tmp_path / "none"), "--words", "ok"]) == 2


def test_bar_confirm_without_yes_writes_nothing(tmp_path: Path, monkeypatch) -> None:
    bar = tmp_path / "bar.yaml"
    bar.write_text(cli.BAR_PATH.read_text())
    monkeypatch.setattr(cli, "BAR_PATH", bar)
    (tmp_path / "b").mkdir()
    (tmp_path / "b" / "summary.json").write_text("{}")
    before = bar.read_text()
    assert cli.main(["bar", "confirm", "--baseline", str(tmp_path / "b"), "--words", "ok"]) == 2
    assert bar.read_text() == before
    assert (
        cli.main(["bar", "confirm", "--baseline", str(tmp_path / "b"), "--words", "ok", "--yes"])
        == 0
    )
    assert yaml.safe_load(bar.read_text())["status"] == "confirmed"


def test_manual_new_records_every_item_not_run(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "0xcc/evaluation").mkdir(parents=True)
    (tmp_path / "0xcc/evaluation/MANUAL_CHECK.md").write_text(
        (cli.REPO_ROOT / "0xcc/evaluation/MANUAL_CHECK.md").read_text()
    )
    monkeypatch.setattr(cli, "REPO_ROOT", tmp_path)
    assert cli.main(["manual", "new", "--release", "0.1.0", "--client", "claude-ai"]) == 0
    doc = yaml.safe_load((tmp_path / "0xcc/evaluation/manual/0.1.0/claude-ai.yaml").read_text())
    assert len(doc["items"]) >= 8 and {i["result"] for i in doc["items"]} == {"not_run"}


def test_publish_writes_figures_only(tmp_path: Path) -> None:
    summary = {
        "schema": "miassist.eval-report/v1",
        "label": "r",
        "generated_utc": "t",
        "headings": [],
        "verdict": "BAR MET",
        "transcript": "secret words",
        "cells": [
            {
                "key": ["a", "b", "c", "d"],
                "successes": 9,
                "valid": 10,
                "bar_calls": {"median": 4},
                "app_answer": "operator data",
            }
        ],
    }
    (tmp_path / "summary.json").write_text(json.dumps(summary))
    assert cli.main(["publish", str(tmp_path)]) == 0
    for name in ("published.json", "PUBLISHED.md"):
        text = (tmp_path / name).read_text()
        assert "secret words" not in text and "operator data" not in text


def test_run_of_an_unlanded_surface_exits_3() -> None:
    assert cli.main(["run", "--tier", "1a"]) == 3


def test_record_refuses_the_steering_goal_on_the_miassist_surface(
    capsys, vectors_without_steering
) -> None:
    """R1 review fix (OR1-002-4), 2026-11-16: "no live miAssist recording of the steering goal" is a
    refusal in ``record`` while the vendored vectors lack the steering rows, before anything else.
    """
    from miassist_eval import gpu_guard
    from tests.support import harness

    # Against vectors without the steering rows (OVN-miassist-int-5): the refusal's own premise.
    assert gpu_guard.goal_incomplete("steering", harness.gpu_list.__wrapped__())  # uncached
    code = cli.main(["record", "--goal", "tone-warmer", "--surface", "miassist"])
    out = capsys.readouterr().out
    assert code == 2 and "gpu_list_incomplete" in out
    # the dataset goal passes the same check and reaches the live-apps refusal instead
    code = cli.main(["record", "--goal", "dataset-refund", "--surface", "miassist"])
    out = capsys.readouterr().out
    assert code == 2 and "gpu_list_incomplete" not in out and "MIASSIST_EVAL_LIVE_APPS" in out


def test_record_takes_the_steering_goal_once_the_vectors_hold_it(capsys) -> None:
    """Integration (OVN-miassist-int-5): with Core's vendored vectors (56, the three ``/async/``
    steering rows) the steering goal passes the GPU-list check and reaches the live-apps refusal."""
    from miassist_eval import gpu_guard
    from tests.support import harness

    assert gpu_guard.goal_incomplete("steering", harness.gpu_list()) == []
    code = cli.main(["record", "--goal", "tone-warmer", "--surface", "miassist"])
    out = capsys.readouterr().out
    assert code == 2 and "gpu_list_incomplete" not in out and "MIASSIST_EVAL_LIVE_APPS" in out
