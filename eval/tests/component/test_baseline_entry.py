"""FR-002.35a (R3M-4): ``record --surface baseline`` refuses, in turn, with each piece Core ships
removed, and records no run; there is no fallback to an empty guard or no filter."""

from __future__ import annotations

from pathlib import Path

import pytest

from miassist_eval import allowed, cli


def run_dir_count() -> int:
    runs = cli.EVAL_ROOT / "runs"
    return len(list(runs.glob("*"))) if runs.exists() else 0


def test_vectors_missing_refuses_gpu_list_missing(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("MIASSIST_WB_PAYLOAD_VECTORS", str(tmp_path / "absent.json"))
    before = run_dir_count()
    assert cli.main(["record", "--goal", "detector-refund", "--surface", "baseline"]) == 2
    assert "gpu_list_missing" in capsys.readouterr().out
    assert run_dir_count() == before


def test_filter_module_missing_refuses(monkeypatch, capsys) -> None:
    monkeypatch.setattr(allowed, "CORE", None)
    monkeypatch.setenv("MIASSIST_REQUIRE_CORE", "0")
    assert cli.main(["record", "--goal", "detector-refund", "--surface", "baseline"]) == 2
    assert "filter_module_missing" in capsys.readouterr().out


def test_cassette_schema_missing_refuses(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("MIASSIST_CORE_CASSETTE_SCHEMA", str(tmp_path / "absent.json"))
    assert cli.main(["record", "--goal", "detector-refund", "--surface", "baseline"]) == 2
    assert "cassette_schema_missing" in capsys.readouterr().out


def test_with_every_piece_present_it_still_refuses_without_live_apps(monkeypatch, capsys) -> None:
    monkeypatch.delenv("MIASSIST_EVAL_LIVE_APPS", raising=False)
    assert cli.main(["record", "--goal", "detector-refund", "--surface", "baseline"]) == 2
    out = capsys.readouterr().out
    assert "workstation" in out and "gpu_list_missing" not in out


@pytest.mark.parametrize("ci", ["CI", "GITHUB_ACTIONS"])
def test_record_refuses_under_ci(ci: str, monkeypatch, capsys) -> None:
    monkeypatch.setenv(ci, "true")
    assert cli.main(["record", "--goal", "detector-refund", "--surface", "baseline"]) == 2
    assert "ci_refused" in capsys.readouterr().out


def test_a_recorder_cannot_be_built_without_cores_module(monkeypatch) -> None:
    from miassist_eval.classes import Refusal
    from miassist_eval.recorder import Recorder
    from tests.support import harness

    monkeypatch.setattr(allowed, "CORE", None)
    with pytest.raises(Refusal):
        Recorder(edge=harness.edge(), forward=None, allowed_set=None, app_versions={}, writing=True)
