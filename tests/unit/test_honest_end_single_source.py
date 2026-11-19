"""One source for the honest end (001 FR-28, AC-28.2; FTASKS 11.8): no module under
``src/miassist/`` other than ``results/honest_end.py`` holds the sentence, and the words live in
``guidance/honest_end.yaml``. The scan reads every string literal (f-string parts joined) so a
sentence split across lines is still found; the self-test plants it."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src/miassist"
OWNER = SRC / "results/honest_end.py"
PHRASES = ("isn't part of this installation", "aren't part of this installation")


def literals(source: str) -> list[str]:
    tree = ast.parse(source)
    out: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            out.append(node.value)
        elif isinstance(node, ast.JoinedStr):
            out.append(
                "".join(
                    v.value
                    for v in node.values
                    if isinstance(v, ast.Constant) and isinstance(v.value, str)
                )
            )
    # implicit concatenation is already one Constant; adjacent f-string pieces are joined above
    return out


def holders(root: Path) -> list[str]:
    found = []
    for path in sorted(root.rglob("*.py")):
        if path == OWNER:
            continue
        text = " ".join(literals(path.read_text(encoding="utf-8"))).lower()
        if any(p in text for p in PHRASES):
            found.append(str(path.relative_to(root)))
    return found


def test_single_source() -> None:
    assert holders(SRC) == []
    words = (SRC / "guidance/honest_end.yaml").read_text()
    assert all(p in words for p in PHRASES)


@pytest.mark.parametrize(
    "plant",
    [
        'X = "That needs miServer, which isn\'t part of this installation."\n',
        'def f(a):\n    return f"needs {a}, which aren\'t part " f"of this installation"\n',
        'X = ("needs miServer, which isn\'t part of "\n     "this installation")\n',
    ],
    ids=["literal", "fstring", "implicit-concatenation"],
)
def test_self_test(tmp_path: Path, plant: str) -> None:
    (tmp_path / "planted.py").write_text(plant)
    assert holders(tmp_path) == ["planted.py"]
