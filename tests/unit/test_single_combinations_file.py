"""Exactly one combinations harness and one table (001 FR-22, AC-22.2; FTASKS 12.3): every chain
adds its rows to ``tests/fixtures/combinations.py`` and its cases to
``tests/harness/test_combinations.py``, never a second file."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HARNESS = re.compile(r"combination", re.IGNORECASE)


def combination_files(tree: Path) -> tuple[list[str], list[str]]:
    tests, tables = [], []
    for path in sorted(tree.rglob("*.py")):
        if not HARNESS.search(path.name):
            continue
        rel = str(path.relative_to(tree))
        if path.name.startswith("test_") and path.name != "test_single_combinations_file.py":
            tests.append(rel)
        elif not path.name.startswith("test_"):
            tables.append(rel)
    return tests, tables


def test_exactly_one() -> None:
    tests, tables = combination_files(ROOT / "tests")
    assert tests == ["harness/test_combinations.py"]
    assert tables == ["fixtures/combinations.py"]


def test_self_test(tmp_path: Path) -> None:
    (tmp_path / "harness").mkdir()
    (tmp_path / "harness/test_combinations.py").write_text("")
    (tmp_path / "harness/test_combinations_steering.py").write_text("")
    (tmp_path / "fixtures").mkdir()
    (tmp_path / "fixtures/combinations.py").write_text("")
    tests, tables = combination_files(tmp_path)
    assert len(tests) == 2 and tables == ["fixtures/combinations.py"]
