"""TI-3: every class string is defined once in classes.py; no stray class literal elsewhere."""

from __future__ import annotations

import ast
import re
from pathlib import Path

from miassist_eval import classes

PKG = Path(classes.__file__).resolve().parent
SUFFIXES = re.compile(
    r"^[a-z]+(_[a-z]+)*_(refused|missing|miss|route|header|decision|limit|loop|refusal|misread|"
    r"stopped|figure|outcome|start|drift|allowed|list|precondition|exceeded|comparable|started|"
    r"connected|error|mismatch|integrity|stale|old|handoff|recording|registered)$"
)


#: Record and profile FIELD names that share a class suffix; listed so the exemption is visible.
FIELD_NAMES = frozenset({"agent_header", "reference_stale", "is_error"})


def literals() -> list[tuple[str, str]]:
    out = []
    for path in PKG.rglob("*.py"):
        if path.name == "classes.py":
            continue
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                out.append((str(path.relative_to(PKG)), node.value))
    return out


def test_the_pattern_finds_class_names() -> None:
    assert all(SUFFIXES.match(c) for c in ("cassette_miss", "unknown_route", "gpu_list_missing"))


def test_no_stray_class_strings() -> None:
    stray = [
        (f, s)
        for f, s in literals()
        if SUFFIXES.match(s) and s not in classes.ALL and s not in FIELD_NAMES
    ]
    assert stray == [], f"class-shaped strings not defined in classes.py: {stray}"


def test_refusal_rejects_an_unknown_class() -> None:
    import pytest

    with pytest.raises(ValueError):
        classes.Refusal("made_up_refused")
    assert classes.Refusal(classes.CASSETTE_STALE, "x").cls == "cassette_stale"
