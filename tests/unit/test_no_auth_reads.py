"""The open endpoint (M11, ADR-005; 001 FR-21, FTASKS 7.5): no module reads an ``Authorization``
header except the log filter, which drops it. Reading a header needs its name as a literal, so the
guard looks for the literal (str or bytes) in the AST, docstrings excluded."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src" / "miassist"
ALLOWED = {"logging.py"}


def header_literals(source: str) -> list[int]:
    tree = ast.parse(source)
    docstrings = {
        id(node.body[0].value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Module | ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef)
        and node.body
        and isinstance(node.body[0], ast.Expr)
        and isinstance(node.body[0].value, ast.Constant)
    }
    hits = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and id(node) not in docstrings:
            value = node.value
            if isinstance(value, bytes):
                value = value.decode(errors="ignore")
            if isinstance(value, str) and value.strip().lower() == "authorization":
                hits.append(node.lineno)
    return hits


def test_source_guard() -> None:
    found = {
        str(p.relative_to(SRC)): header_literals(p.read_text())
        for p in SRC.rglob("*.py")
        if p.name not in ALLOWED
    }
    assert not {k: v for k, v in found.items() if v}


@pytest.mark.parametrize(
    "source",
    [
        't = request.headers.get("authorization")\n',
        "a = h[b'Authorization']\n",
        'x = {"AUTHORIZATION"}\n',
    ],
)
def test_source_guard_self_test(source: str) -> None:
    assert header_literals(source)


def test_docstring_mention_is_not_a_read() -> None:
    assert not header_literals('"""The Authorization header is ignored."""\n')
