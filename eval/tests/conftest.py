"""Evaluation tests (FTID §8). Run from eval/: `.venv/bin/python -m pytest -n 4 --dist loadfile`."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

EVAL_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = EVAL_ROOT.parent
CASSETTE_ROOT = REPO_ROOT / "tests" / "fixtures" / "cassettes" / "private" / "eval"


@pytest.fixture
def cassette_root() -> Path:
    """The committed eval cassette root. Absent: a LOUD skip, or a failure under
    ``MIASSIST_REQUIRE_CASSETTES=1`` (FR-002.14)."""
    if not (CASSETTE_ROOT / "INDEX.json").is_file():
        message = f"no approved take under {CASSETTE_ROOT}"
        if os.environ.get("MIASSIST_REQUIRE_CASSETTES") == "1":
            pytest.fail(f"MIASSIST_REQUIRE_CASSETTES=1 and {message}")
        pytest.skip(f"LOUD SKIP: {message} (MIASSIST_REQUIRE_CASSETTES=1 makes this a failure)")
    return CASSETTE_ROOT


@pytest.fixture(autouse=True)
def _no_ci_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tests decide CI themselves; the CI guard is tested with these set explicitly."""
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)


def pytest_report_header(config: pytest.Config) -> str:
    return f"miassist-eval: python {sys.version.split()[0]}; cassette root {CASSETTE_ROOT}"


@pytest.fixture
def vectors_without_steering(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Integration (OVN-miassist-int-5), 2026-11-16: Core's vendored vectors now hold the three
    ``/async/`` steering rows (045-A0 @ fdb53989a, 56 vectors), so the steering refusal lifted by
    itself. The refusal MECHANISM stays pinned against this copy of the vendored file with every
    ``steer_*`` row removed (the state the refusal was written for)."""
    from miassist_eval import gpu_guard

    doc = json.loads(gpu_guard.DEFAULT_VECTORS.read_text(encoding="utf-8"))
    kept = [v for v in doc["vectors"] if not str(v.get("action", "")).startswith("steer_")]
    assert len(kept) < len(doc["vectors"]), "the vendored vectors hold no steering row"
    doc["vectors"] = kept
    path = tmp_path / "vectors-without-steering.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    monkeypatch.setenv("MIASSIST_WB_PAYLOAD_VECTORS", str(path))
    return path
