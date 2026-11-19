"""FR-002.3: the harness is not in the miAssist image (read from the build context after
.dockerignore, until an image exists)."""

from __future__ import annotations

import fnmatch
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]


def ignored(rel: str, patterns: list[str]) -> bool:
    result = False
    for pat in patterns:
        negate = pat.startswith("!")
        p = pat[1:] if negate else pat
        p = p.rstrip("/")
        if fnmatch.fnmatch(rel, p) or fnmatch.fnmatch(rel, p + "/*") or rel.split("/")[0] == p:
            result = not negate
    return result


def patterns() -> list[str]:
    lines = (REPO / ".dockerignore").read_text().splitlines()
    return [ln.strip() for ln in lines if ln.strip() and not ln.startswith("#")]


def test_eval_is_outside_the_build_context() -> None:
    pats = patterns()
    for rel in ("eval/miassist_eval/__init__.py", "eval/pyproject.toml", "eval/goals.yaml"):
        assert ignored(rel, pats), f"{rel} would be sent to the image build"


def test_the_matcher_still_sends_the_server() -> None:
    assert not ignored("src/miassist/__init__.py", patterns())


def test_no_dockerfile_copies_eval() -> None:
    text = (REPO / "Dockerfile").read_text()
    assert "eval" not in [w.strip("/.") for w in text.split()], "the Dockerfile names eval/"
