"""Every requirement is pinned exactly (PADR ADR-002; Foundation task 1.1).

A range lets CI, the image and a developer venv resolve different releases on different days
(suite memory ``dev-venv-vs-image-version-drift``). ``mcp`` is pinned to the apps' 2.3.0.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
PYPROJECT = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text())
EXACT = re.compile(r"^[A-Za-z0-9_.\-]+(\[[A-Za-z0-9_,\-]+\])?==[A-Za-z0-9_.+\-]+$")


def requirements() -> list[str]:
    project = PYPROJECT["project"]
    reqs = list(project["dependencies"])
    for extra in project.get("optional-dependencies", {}).values():
        reqs += extra
    reqs += PYPROJECT["build-system"]["requires"]
    return reqs


def test_there_are_requirements() -> None:
    assert len(requirements()) > 10


@pytest.mark.parametrize("req", requirements())
def test_requirement_is_pinned_exactly(req: str) -> None:
    assert EXACT.match(req.replace(" ", "")), f"{req!r} is not pinned with == (ADR-002)"


def test_mcp_is_the_apps_version() -> None:
    assert "mcp==2.3.0" in PYPROJECT["project"]["dependencies"]
