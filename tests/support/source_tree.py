# Origin: miDataworks (Onegaishimas/miDataworks) backend/tests/support/source_tree.py @ a94d99bf
# Mode: adapt (docs/REUSE.md). Kept: skip only on the mirror snapshot (a parentless HEAD with the
# sync's `Source-Commit:` / `Private-CI: passed` trailers), fail everywhere else; a shipping file
# that is missing always fails. Changed: miAssist's sync-to-clean.yml keeps its strip as a shell
# step, not an env list, so "stripped" is decided by RUNNING that step over a planted tree; a
# per-entry form (`source_present`) for allow-lists that name stripped files.
"""What the public mirror strips, and a loud skip for it (mirror fix 001-M, 2026-11-16).

The mirror (``hitsainet/miAssist``) is an orphan snapshot with ``0xcc/``, ``AGENT.md``,
``CLAUDE.md``, ``GEMINI.md``, ``scripts/private/``, every cassette tree and every ``docs/`` entry but
``schemas/`` and ``REUSE.md`` removed, and it runs the backend suite, because its image build is
gated on that run. At 07d65a3 four tests read ``0xcc/`` and the mirror's Backend Tests went red.

So a test that reads a stripped file goes through :func:`source_only` (or, for one entry of a list,
:func:`source_present`), which:

- returns the path when the file exists;
- FAILS when the file is missing and the sync does not strip it (a shipping file must exist);
- FAILS when the file is missing from any tree that is not the mirror snapshot (this repository, a
  worktree, the private CI): the private CI is the gate, and nothing may skip there for want of a
  file the mirror lacks;
- skips LOUDLY (``SOURCE-ONLY: ...``) only on the mirror snapshot.

"Stripped" is never a second hand-kept list: :func:`stripped_by_mirror` runs the workflow's own
"Remove excluded files and folders" step over a temporary tree that holds the asked paths and reads
back which ones it removed. ``tests/unit/test_source_tree.py`` holds the guard and its controls, and
refuses a test module that names an existing stripped file without going through this helper.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tempfile
import warnings
from collections.abc import Iterable
from functools import lru_cache
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
SYNC_WORKFLOW = REPO / ".github" / "workflows" / "sync-to-clean.yml"
STRIP_STEP = "Remove excluded files and folders"
CASSETTE_STRIP = REPO / ".github" / "scripts" / "cassette_strip.py"


def strip_step_script() -> str:
    """The strip step's shell text, from the PARSED workflow (the authority)."""
    doc: dict[str, Any] = yaml.safe_load(SYNC_WORKFLOW.read_text(encoding="utf-8"))
    step = next(s for s in doc["jobs"]["sync"]["steps"] if s.get("name") == STRIP_STEP)
    script: str = step["run"]
    return script


def stripped_set(rels: Iterable[str]) -> frozenset[str]:
    """Which of ``rels`` (repo-relative POSIX paths) the sync's strip step removes: each is planted
    as a one-line text file in a temporary tree, the step runs there, and a path gone afterwards is
    stripped. A step that fails (it refuses anything cassette-like) raises: never a silent answer.
    """
    names = sorted({r.strip("/") for r in rels})
    with tempfile.TemporaryDirectory(prefix="miassist-strip-") as tmp:
        root = Path(tmp)
        for name in names:
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("planted\n", encoding="utf-8")
        (root / ".github/scripts").mkdir(parents=True, exist_ok=True)
        shutil.copy(CASSETTE_STRIP, root / ".github/scripts/cassette_strip.py")
        script = strip_step_script().replace("python3 ", sys.executable + " -I ")
        result = subprocess.run(
            ["bash", "-c", script], cwd=root, capture_output=True, text=True, check=False
        )
        assert result.returncode == 0, (
            "the sync's strip step failed over planted placeholder files:\n"
            + result.stdout
            + result.stderr
        )
        return frozenset(n for n in names if not (root / n).exists())


@lru_cache(maxsize=256)
def stripped_by_mirror(rel: str) -> bool:
    """True when sync-to-clean.yml removes ``rel`` from the mirror."""
    return rel.strip("/") in stripped_set([rel])


_SOURCE_COMMIT = re.compile(r"^Source-Commit: [0-9a-f]{40}$", re.M)


def mirror_snapshot(root: Path | None = None) -> bool:
    """True only when ``root``'s HEAD is the snapshot sync-to-clean.yml publishes: a commit with NO
    parent carrying the ``Source-Commit: <sha>`` and ``Private-CI: passed`` trailers written by the
    sync's "Build the orphan snapshot" step (and required by the mirror's image build). A commit of
    this repository has a parent and no such trailers; a shallow clone of it (what CI checks out)
    shows no parent but still lacks the trailers. No git, or no repository: False."""
    root = REPO if root is None else root
    try:
        parents = subprocess.run(
            ["git", "rev-list", "--parents", "-n", "1", "HEAD"],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
        )
        trailers = subprocess.run(
            ["git", "log", "-1", "--format=%(trailers:only,unfold)", "HEAD"],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
        )
    except (FileNotFoundError, NotADirectoryError):
        return False
    if parents.returncode != 0 or trailers.returncode != 0:
        return False
    if len(parents.stdout.split()) != 1:
        return False
    lines = trailers.stdout.splitlines()
    return "Private-CI: passed" in lines and bool(_SOURCE_COMMIT.search(trailers.stdout))


def _absent_reason(rel: str, root: Path) -> str:
    """Why ``rel`` may be absent from ``root`` (only on the mirror); raise AssertionError otherwise."""
    assert stripped_by_mirror(rel), (
        f"{rel} is missing, and sync-to-clean.yml does not strip it from the mirror. A shipping "
        "file must exist; this is a failure, not a skip."
    )
    assert mirror_snapshot(root), (
        f"{rel} is missing from a tree that is not the mirror snapshot (HEAD is not a parentless "
        "commit with 'Source-Commit' / 'Private-CI: passed' trailers). Only the mirror may lack "
        "it; this is a failure, not a skip."
    )
    return (
        f"SOURCE-ONLY: {rel} is stripped from the public mirror by sync-to-clean.yml, so this "
        "check runs only in the private repository."
    )


def source_only(rel: str, root: Path | None = None) -> Path:
    """The path to a file the mirror strips. Present: returned. Absent: skip LOUDLY on the mirror
    snapshot, fail anywhere else (see the module docstring)."""
    root = REPO if root is None else root
    path = root / rel
    if path.exists():
        return path
    pytest.skip(_absent_reason(rel, root))


def source_present(rel: str, root: Path | None = None) -> bool:
    """For one entry of a list that names files (an allow-list): True when the file exists; False,
    with a warning, only on the mirror snapshot for a file the sync strips; a failure otherwise.
    The rest of the test still runs on the mirror."""
    root = REPO if root is None else root
    if (root / rel).exists():
        return True
    warnings.warn(_absent_reason(rel, root), stacklevel=2)
    return False
