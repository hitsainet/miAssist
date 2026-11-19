"""Tests that read a file the public mirror strips skip there, loudly, and never anywhere else
(mirror fix 001-M, 2026-11-16).

At 07d65a3 the private CI was green and ``hitsainet/miAssist``'s Backend Tests were red: four tests
read ``0xcc/``, which the sync removes. ``tests/support/source_tree.py`` is the one way such a test
reads its file. This module holds it to its rules:

- "stripped" is what the workflow's own strip step removes (run, not re-listed);
- the mirror snapshot is recognised only by its parentless, trailer-carrying HEAD;
- a missing stripped file FAILS in any other tree (the private repository, a worktree, the private
  CI), and a missing shipping file fails everywhere;
- a tree without ``0xcc/`` is the mirror snapshot, or this module fails;
- every test module that names an existing stripped file goes through the helper (an AST read of
  string constants, so a comment never satisfies it).
"""

from __future__ import annotations

import ast
import os
import subprocess
import warnings
from collections.abc import Callable
from pathlib import Path

import pytest

from tests.support import source_tree
from tests.support.source_tree import (
    REPO,
    mirror_snapshot,
    source_only,
    source_present,
    stripped_by_mirror,
    stripped_set,
)

SHA = "0123456789abcdef0123456789abcdef01234567"
GIT_ENV = {**os.environ, "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1"}


def git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True, env=GIT_ENV, capture_output=True)


def commit(root: Path, message: str) -> None:
    git(root, "add", "-A")
    git(
        root,
        "-c",
        "user.name=t",
        "-c",
        "user.email=t@example.invalid",
        "commit",
        "-q",
        "-m",
        message,
    )


SNAPSHOT_MESSAGE = f"snapshot\n\nSource-Commit: {SHA}\nPrivate-CI: passed"


def make_tree(root: Path, *, parent: bool, trailers: bool, files: dict[str, str]) -> Path:
    """A one- or two-commit repository holding ``files``."""
    root.mkdir(parents=True, exist_ok=True)
    git(root, "init", "-q", "-b", "main")
    if parent:
        (root / "first.txt").write_text("first\n")
        commit(root, "first")
    for name, text in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    (root / "README.md").write_text("# tree\n")
    commit(root, SNAPSHOT_MESSAGE if trailers else "an ordinary commit")
    return root


# ---- "stripped" comes from the workflow's strip step -----------------------------------------


STRIPPED = [
    "0xcc/prds/001_FPRD|Core.md",
    "0xcc/tids/002_FTID|Evaluation.md",
    "AGENT.md",
    "CLAUDE.md",
    "GEMINI.md",
    ".claude/settings.json",
    "backups/db.sql",
    "scripts/private/record.sh",
    "docs/reviews/r1.md",
    "docs/guide.md",
    "tests/fixtures/cassettes/private/a.json",
]
KEPT = [
    "docs/schemas/README.md",
    "docs/REUSE.md",
    "README.md",
    "scripts/write_contracts.py",
    "src/miassist/__init__.py",
    "tests/unit/test_reachability.py",
    "manual/docs/intro.md",
]


def test_stripped_is_what_the_strip_step_removes() -> None:
    assert stripped_set(STRIPPED + KEPT) == frozenset(STRIPPED)
    assert stripped_by_mirror("0xcc/tasks/000_FTASKS|Project_Foundation.md")
    assert not stripped_by_mirror("tests/unit/test_cited_tests_exist.py")


# ---- the mirror snapshot is recognised by its HEAD alone -------------------------------------


def test_mirror_snapshot_needs_no_parent_and_both_trailers(tmp_path: Path) -> None:
    assert mirror_snapshot(make_tree(tmp_path / "m", parent=False, trailers=True, files={}))
    assert not mirror_snapshot(make_tree(tmp_path / "p", parent=True, trailers=True, files={}))
    assert not mirror_snapshot(make_tree(tmp_path / "t", parent=False, trailers=False, files={}))
    one = make_tree(tmp_path / "one", parent=False, trailers=False, files={})
    (one / "x").write_text("x\n")
    commit(one, f"snapshot\n\nSource-Commit: {SHA}")  # has a parent now, and one trailer
    assert not mirror_snapshot(one)
    half = tmp_path / "half"
    half.mkdir()
    git(half, "init", "-q", "-b", "main")
    (half / "x").write_text("x\n")
    commit(half, "snapshot\n\nPrivate-CI: passed")  # parentless, no Source-Commit
    assert not mirror_snapshot(half)
    (tmp_path / "plain").mkdir()
    assert not mirror_snapshot(tmp_path / "plain")  # not a repository


def test_a_tree_without_the_planning_chain_is_the_mirror() -> None:
    """Both directions, in THIS checkout: the mirror never carries ``0xcc/``, and a tree that lacks
    it must be the mirror snapshot. A private run with ``0xcc/`` deleted fails here even if no
    reader of it is collected."""
    has_chain = (REPO / "0xcc").is_dir()
    assert has_chain is not mirror_snapshot(), (
        f"0xcc/ present: {has_chain}; mirror snapshot: {mirror_snapshot()}. Only the mirror "
        "snapshot may lack the planning chain, and it never carries it."
    )


# ---- source_only / source_present: skip only on the mirror, fail everywhere else --------------


REL = "0xcc/prds/001_FPRD|Core.md"


def outcome(fn: Callable[[str, Path], object], rel: str, root: Path) -> tuple[str, str]:
    """What a call does, with a skip caught as itself: a skip inside ``pytest.raises`` would
    propagate and SKIP the guard instead of turning it red (found by control M1)."""
    try:
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            value = fn(rel, root)
    except AssertionError as exc:
        return "fail", str(exc)
    except pytest.skip.Exception as exc:
        return "skip", str(exc)
    return f"returned {value!r}", " ".join(str(w.message) for w in caught)


def test_present_file_is_returned(tmp_path: Path) -> None:
    root = make_tree(tmp_path / "r", parent=True, trailers=False, files={REL: "# prd\n"})
    assert outcome(source_only, REL, root) == (f"returned {root / REL!r}", "")
    assert outcome(source_present, REL, root) == ("returned True", "")


def test_missing_stripped_file_fails_in_a_private_tree(tmp_path: Path) -> None:
    """THE guard: a tree that is not the mirror snapshot (a parent, or no trailers) without the
    file FAILS, never skips and never passes over it."""
    for name, parent, trailers in (("p", True, False), ("pt", True, True), ("o", False, False)):
        root = make_tree(tmp_path / name, parent=parent, trailers=trailers, files={})
        for fn in (source_only, source_present):
            kind, message = outcome(fn, REL, root)
            assert kind == "fail", (name, fn.__name__, kind, message)
            assert "not the mirror snapshot" in message, message


def test_missing_stripped_file_skips_loudly_on_the_mirror(tmp_path: Path) -> None:
    root = make_tree(tmp_path / "m", parent=False, trailers=True, files={})
    kind, message = outcome(source_only, REL, root)
    assert kind == "skip" and message.startswith(f"SOURCE-ONLY: {REL} "), (kind, message)
    kind, message = outcome(source_present, REL, root)
    assert kind == "returned False" and message.startswith(f"SOURCE-ONLY: {REL} "), (kind, message)


def test_missing_shipping_file_fails_even_on_the_mirror(tmp_path: Path) -> None:
    root = make_tree(tmp_path / "m", parent=False, trailers=True, files={})
    for rel in ("docs/schemas/gone.json", "src/miassist/gone.py"):
        for fn in (source_only, source_present):
            kind, message = outcome(fn, rel, root)
            assert kind == "fail" and "does not strip it" in message, (rel, fn.__name__, message)


# ---- every reader of a stripped file goes through the helper ---------------------------------


#: A module whose stripped paths are data read by another module: (data module, its reader).
DATA_ONLY = {
    "tests/support/secret_scan.py": "tests/unit/test_no_secrets_tracked.py",
}
HELPER = "tests.support.source_tree"
#: Exact (module, stripped file) pairs that name the file without reading it, each with why. A new
#: entry is a reviewed change; a stale one fails ``test_not_reads_are_current``.
NOT_READS = {
    ("tests/unit/test_mirror_strip.py", name): "plants the name in a temporary tree and lists "
    "the strip step's excluded files; reads nothing from this checkout"
    for name in ("AGENT.md", "CLAUDE.md", "GEMINI.md")
}


def string_constants(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return {
        n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)
    }


def imports_helper(path: Path) -> bool:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == HELPER:
            return True
        if (
            isinstance(node, ast.ImportFrom)
            and node.module == "tests.support"
            and any(a.name == "source_tree" for a in node.names)
        ):
            return True
        if isinstance(node, ast.Import) and any(a.name == HELPER for a in node.names):
            return True
    return False


def stripped_readers(root: Path) -> dict[str, set[str]]:
    """Each module under ``tests/`` (but this one and the helper) -> the existing files the mirror
    strips that it names in a string constant."""
    named: dict[str, set[str]] = {}
    for path in sorted((root / "tests").rglob("*.py")):
        rel = path.relative_to(root).as_posix()
        if rel in ("tests/unit/test_source_tree.py", "tests/support/source_tree.py"):
            continue
        hits = {c for c in string_constants(path) if "\n" not in c and (root / c).is_file()}
        if hits:
            named[rel] = hits
    every = set().union(*named.values()) if named else set()
    stripped = stripped_set(every) if every else frozenset()
    return {m: s & stripped for m, s in named.items() if s & stripped}


def unguarded(root: Path) -> list[str]:
    bad = []
    for module, names in stripped_readers(root).items():
        if all((module, n) in NOT_READS for n in names):
            continue
        reader = DATA_ONLY.get(module, module)
        if not imports_helper(root / reader):
            bad.append(reader)
    return sorted(set(bad))


def test_every_reader_of_a_stripped_file_uses_the_helper() -> None:
    # on the mirror the files are gone and there is nothing to find: skip there, loudly
    source_only("0xcc/tasks/001_FTASKS|Core.md")
    readers = stripped_readers(REPO)
    # not vacuous: the four readers of 07d65a3 are found (through secret_scan's allow-list too)
    assert {
        "tests/unit/test_reachability.py",
        "tests/unit/test_cited_tests_exist.py",
        "tests/support/secret_scan.py",
        "tests/unit/test_no_secrets_tracked.py",
    } <= set(readers), readers
    assert unguarded(REPO) == [], "read stripped files through tests/support/source_tree.py"


def test_not_reads_are_current() -> None:
    source_only("0xcc/tasks/001_FTASKS|Core.md")  # the pairs name files only this checkout has
    named = {(m, n) for m, names in stripped_readers(REPO).items() for n in names}
    assert set(NOT_READS) <= named, sorted(set(NOT_READS) - named)


def test_reader_guard_self_test(tmp_path: Path) -> None:
    (tmp_path / "0xcc/prds").mkdir(parents=True)
    (tmp_path / "0xcc/prds/a.md").write_text("# a\n")
    (tmp_path / "tests/unit").mkdir(parents=True)
    (tmp_path / "tests/support").mkdir(parents=True)
    raw = 'from pathlib import Path\n\nTEXT = Path("0xcc/prds/a.md")  # 0xcc/prds/a.md\n'
    (tmp_path / "tests/unit/test_raw.py").write_text(raw)
    (tmp_path / "tests/unit/test_comment.py").write_text("# reads 0xcc/prds/a.md\n")
    (tmp_path / "tests/unit/test_fixture.py").write_text('NAME = "0xcc/tasks/not-a-file.md"\n')
    assert unguarded(tmp_path) == ["tests/unit/test_raw.py"]
    (tmp_path / "tests/unit/test_raw.py").write_text(
        "from tests.support.source_tree import source_only\n\n"
        'TEXT = source_only("0xcc/prds/a.md")\n'
    )
    assert unguarded(tmp_path) == []
    (tmp_path / "tests/support/secret_scan.py").write_text('KNOWN = {("0xcc/prds/a.md", "x")}\n')
    (tmp_path / "tests/unit/test_no_secrets_tracked.py").write_text("X = 1\n")
    assert unguarded(tmp_path) == ["tests/unit/test_no_secrets_tracked.py"]


def test_helper_reads_the_workflow_it_names() -> None:
    assert source_tree.SYNC_WORKFLOW.is_file()
    assert "rm -rf 0xcc/" in source_tree.strip_step_script()
