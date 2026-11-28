"""The default run collects no ``cross_repo`` or ``live`` test (Foundation task 1.8)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _collect(*extra: str) -> str:
    return subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:xdist", *extra],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    ).stdout


def test_default_run_deselects_both_markers() -> None:
    default = _collect("tests/cross_repo")
    assert "test_sibling_checked_out" not in default
    marked = _collect("tests/cross_repo", "-m", "cross_repo")
    assert (
        "test_sibling_checked_out" in marked
    ), "the cross_repo test is not collected even when asked"


def test_addopts_deselects_live() -> None:
    import tomllib

    addopts = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text())["tool"]["pytest"][
        "ini_options"
    ]["addopts"]
    assert "not cross_repo" in addopts and "not live" in addopts
