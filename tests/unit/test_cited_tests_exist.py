"""No ticked task cites a test that does not exist (R1 review fix OR1-001-6; R2 review fix OR2-001-6,
2026-11-16: every format, and an unknown format fails).

Round 1 found seventeen cited test files missing: tests consolidated, citations not updated. Round 2
found the first guard read one citation format and silently skipped the rest (54 of 116 mentions).
So the guard is inverted: in every ticked (``[x]`` or ``[X]``) sub-task of the Foundation and 001
task lists, EVERY mention of a test must resolve, in any of these formats:

- a file, with or without ``tests/`` and with any folder, or bare (``test_x.py``, found by glob
  under ``tests/``), inside backticks (a ``pytest ...`` command included) or in plain text;
- ``file::test_name``, ``file::Class::test_name``, with a ``[param]`` id or a ``*`` wildcard;
- a following ``::test_name``: defined in the last file cited before it in the item, else in a file
  cited later in the same item (12.2 names its file after the test); with no file in the item at
  all it is a failure;
- a bare ``test_name`` (no file): defined in one of the item's files or anywhere under ``tests/``.

A backticked span wrapped across lines is read as one span.

A backticked span that mentions ``test_`` in none of these formats FAILS (named in the message),
unless it is listed exactly in ``NOT_CITATIONS`` (identifiers that merely contain ``test_``).

The task lists are in ``0xcc/``, which the public mirror strips: they are read through
``source_only``, which skips loudly there and fails anywhere else they are missing (001-M).
"""

from __future__ import annotations

import re
from pathlib import Path

from tests.support.source_tree import source_only

ROOT = Path(__file__).resolve().parents[2]
TASKS = ("0xcc/tasks/000_FTASKS|Project_Foundation.md", "0xcc/tasks/001_FTASKS|Core.md")

#: Backticked spans that contain ``test_`` but cite no Core test (exact text, without the
#: backticks), each with why. A new entry is a reviewed change.
NOT_CITATIONS = {
    "steering.test_chat": "a miServer route id, not a test",
    "test_id_filter_vectors.py": "feature 002's own test, in 002's chain",
}

_NAME = r"[A-Za-z_][A-Za-z0-9_]*"
_TAIL = r"(?:\[[^\]`]*\]|\*)*"
#: A file citation, optionally with ``::`` parts and a parameter id or wildcard.
FILE_CITE = re.compile(
    rf"(?<![\w/.])(?:tests/)?((?:[a-z0-9_]+/)*test_[a-z0-9_]+\.py)((?:::{_NAME})*){_TAIL}"
)
FOLLOW_CITE = re.compile(rf"(?<![\w.\]])::(test_[a-z0-9_]+)(\*?){_TAIL}")
BARE_CITE = re.compile(rf"^(test_[a-z0-9_]+)(\*?){_TAIL}$")
COMMAND = re.compile(r"^(?:python -m )?pytest\b")
ITEM = re.compile(r"^\s*- \[[ xX?]\] (?:\*\*)?\d")
TICKED = re.compile(r"^\s*- \[[xX]\] ")
DEFINED = re.compile(rf"^\s*(?:async )?def (test_[a-z0-9_]+)|^\s*class ({_NAME})", re.M)


def ticked_items(text: str) -> list[str]:
    items: list[str] = []
    current: list[str] | None = None
    for line in text.splitlines():
        if ITEM.match(line):
            if current is not None:
                items.append("\n".join(current))
            current = [line] if TICKED.match(line) else None
        elif current is not None:
            if line.startswith(("#", "|", "---")):
                items.append("\n".join(current))
                current = None
            else:
                current.append(line)
    if current is not None:
        items.append("\n".join(current))
    return items


def defined_in(path: Path) -> set[str]:
    return {a or b for a, b in DEFINED.findall(path.read_text(encoding="utf-8"))}


def resolve_file(rel: str, root: Path) -> list[Path]:
    tests = root / "tests"
    if "/" in rel:
        path = tests / rel
        return [path] if path.is_file() else []
    return sorted(p for p in tests.rglob(rel) if p.is_file())


def has(names: set[str], name: str, wildcard: bool) -> bool:
    return any(d == name or (wildcard and d.startswith(name)) for d in names)


def missing_in(text: str, root: Path) -> list[str]:
    missing: list[str] = []
    for item in ticked_items(text):
        # A backticked span wrapped across lines is one span.
        item = re.sub(r"`[^`]*`", lambda m: re.sub(r"\s*\n\s*", "", m.group(0)), item)
        # Every file the item cites, in order, with where it is cited.
        files: list[tuple[int, Path]] = []
        for match in FILE_CITE.finditer(item):
            if match.group(0) in NOT_CITATIONS:
                continue
            found = resolve_file(match.group(1), root)
            if not found:
                missing.append(match.group(1))
                continue
            names: set[str] = set().union(*(defined_in(p) for p in found))
            for part in match.group(2).split("::")[1:]:
                wildcard = match.group(0).endswith("*") and not match.group(0).endswith("[*]")
                if not has(names, part, wildcard):
                    missing.append(f"{match.group(1)}::{part}")
            files += [(match.start(), p) for p in found]
        for match in FOLLOW_CITE.finditer(item):
            name, wildcard = match.group(1), bool(match.group(2))
            before = [p for at, p in files if at < match.start()]
            after = [p for at, p in files if at > match.start()]
            if not before and not after:
                missing.append(f"::{name} (no file cited in its item)")
            elif before and has(defined_in(before[-1]), name, wildcard):
                continue
            elif not any(has(defined_in(p), name, wildcard) for p in after):
                where = (before or after)[-1].relative_to(root / "tests")
                missing.append(f"{where}::{name}")
        for span in re.findall(r"`([^`]+)`", item):
            if "test_" not in span or span in NOT_CITATIONS:
                continue
            body = COMMAND.sub("", span).strip()
            if FILE_CITE.fullmatch(body) or FOLLOW_CITE.fullmatch(body):
                continue  # checked above
            bare = BARE_CITE.match(body)
            if bare is None:
                missing.append(f"unknown citation format: `{span}`")
                continue
            name, wildcard = bare.group(1), bool(bare.group(2))
            pool = [p for _, p in files] + sorted((root / "tests").rglob("test_*.py"))
            if not any(has(defined_in(p), name, wildcard) for p in pool):
                missing.append(name)
    return missing


def test_every_cited_test_exists() -> None:
    found = []
    for name in TASKS:
        found += missing_in(source_only(name).read_text(encoding="utf-8"), ROOT)
    assert found == [], f"ticked tasks cite tests that do not exist: {sorted(set(found))}"


def test_tasks_cite_tests() -> None:
    """Not vacuous: the lists cite many tests in each format."""
    text = "\n".join(source_only(n).read_text(encoding="utf-8") for n in TASKS)
    items = "\n".join(ticked_items(text))
    assert len(FILE_CITE.findall(items)) > 100
    assert len(FOLLOW_CITE.findall(items)) > 30


GOOD = """class TestA:
    def test_in_class(self):
        pass


def test_here():
    pass


async def test_param_case():
    pass
"""


def plant(root: Path) -> None:
    (root / "tests/unit").mkdir(parents=True)
    (root / "tests/harness").mkdir(parents=True)
    (root / "tests/unit/test_real.py").write_text(GOOD)
    (root / "tests/harness/test_other.py").write_text("def test_there():\n    pass\n")


#: Each format, once resolving (kept) and once not (the failure it must produce).
FORMATS = [
    ("`unit/test_real.py`", "`unit/test_absent.py`", "unit/test_absent.py"),
    ("`tests/unit/test_real.py`", "`tests/unit/test_absent.py`", "unit/test_absent.py"),
    ("`test_real.py`", "`test_absent.py`", "test_absent.py"),
    (
        "`pytest tests/unit/test_real.py`",
        "`pytest tests/unit/test_absent.py`",
        "unit/test_absent.py",
    ),
    ("plain unit/test_real.py text", "plain unit/test_absent.py text", "unit/test_absent.py"),
    (
        "`unit/test_real.py::test_here`",
        "`unit/test_real.py::test_gone`",
        "unit/test_real.py::test_gone",
    ),
    ("`test_real.py::test_here[x-1]`", "`test_real.py::test_gone[x-1]`", "test_real.py::test_gone"),
    (
        "`unit/test_real.py::test_he*`",
        "`unit/test_real.py::test_go*`",
        "unit/test_real.py::test_go",
    ),
    (
        "`unit/test_real.py::TestA::test_in_class`",
        "`unit/test_real.py::TestA::test_gone`",
        "unit/test_real.py::test_gone",
    ),
    (
        "`unit/test_real.py`, `::test_here`",
        "`unit/test_real.py`, `::test_gone`",
        "unit/test_real.py::test_gone",
    ),
    (
        "`::test_here` (see `unit/test_real.py`)",
        "`::test_gone` (see `unit/test_real.py`)",
        "unit/test_real.py::test_gone",
    ),
    ("`unit/test_real.py` `test_param_case[a]`", "`unit/test_real.py` `test_gone[a]`", "test_gone"),
    ("`test_there`", "`test_nowhere`", "test_nowhere"),
    ("`harness/test_other.py::test_there`", "`e2e/test_other.py::test_there`", "e2e/test_other.py"),
    ("`unit/test_real.py`", "`::test_here`", "::test_here (no file cited in its item)"),
    ("`unit/test_real.py`", "`unit/test_real.py:test_here`", "unknown citation format"),
    (
        "`unit/test_real.py::\n    test_here`",
        "`unit/test_real.py::\n    test_gone`",
        "unit/test_real.py::test_gone",
    ),
]


def test_self_test_every_format(tmp_path: Path) -> None:
    plant(tmp_path)
    for good, bad, expected in FORMATS:
        for marker in ("- [x] 1.1", "- [X] 1.1", "- [x] **1.1**"):
            assert missing_in(f"{marker} {good}.\n", tmp_path) == [], (marker, good)
            found = missing_in(f"{marker} {bad}.\n", tmp_path)
            assert any(expected in f for f in found), (marker, bad, found)


def test_unticked_items_are_not_checked(tmp_path: Path) -> None:
    plant(tmp_path)
    text = "- [ ] 1.2 `unit/test_unticked.py`.\n- [?] 1.3 `unit/test_blocked.py`.\n"
    assert missing_in(text, tmp_path) == []
