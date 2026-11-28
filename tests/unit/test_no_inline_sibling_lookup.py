"""No test computes a sibling path itself (Foundation task 1.3; miForge's rule).

Every sibling is found through ``tests/support/siblings.py``. A test that writes
``Path(__file__).parents[3] / "miServer"`` or reads ``MISERVER_REPO`` itself disagrees with the
lookup's rules the first time a variable is set.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

TESTS = Path(__file__).resolve().parents[1]
LOOKUP = TESTS / "support" / "siblings.py"
FOLDERS = ("miWorkbench", "miServer", "miDataworks", "miForge", "miLLM", "miStudio")
PATTERNS = [
    re.compile(r"""/\s*["'](""" + "|".join(FOLDERS) + r""")["']"""),
    re.compile(r"""["'](MIWORKBENCH|MISERVER|MIDATAWORKS|MIFORGE|MILLM|MISTUDIO)_REPO["']"""),
    re.compile(r"""["']MIASSIST_(MIWORKBENCH|MISERVER|MIDATAWORKS|MIFORGE)_ROOT["']"""),
]
#: Tests that NAME a variable to exercise the lookup itself (not to find a sibling).
EXEMPT = {TESTS / "unit" / "test_sibling_lookup.py", Path(__file__).resolve()}


def offending_lines(source: str) -> list[str]:
    return [line for line in source.splitlines() if any(p.search(line) for p in PATTERNS)]


def scanned_files() -> list[Path]:
    return sorted(p for p in TESTS.rglob("*.py") if p != LOOKUP and p not in EXEMPT)


def test_tree_is_scanned() -> None:
    assert len(scanned_files()) > 5


@pytest.mark.parametrize("path", scanned_files(), ids=lambda p: str(p.relative_to(TESTS)))
def test_no_inline_lookup(path: Path) -> None:
    hits = offending_lines(path.read_text(encoding="utf-8"))
    assert not hits, f"{path.name} finds a sibling itself; use tests/support/siblings.py: {hits}"


@pytest.mark.parametrize(
    "source",
    [
        'root = Path(__file__).parents[3] / "miServer"\n',
        "root = base / 'miForge'\n",
        'os.environ.get("MIDATAWORKS_REPO")\n',
        'os.environ["MIASSIST_MIWORKBENCH_ROOT"]\n',
    ],
)
def test_scanner_sees_each_form(source: str) -> None:
    assert offending_lines(source), f"the scanner missed: {source!r}"
