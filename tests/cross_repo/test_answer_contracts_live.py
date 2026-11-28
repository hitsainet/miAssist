"""The sibling side of feature 006 (ENH-013; FR-006.1, FR-006.2, FR-006.7).

- **Error codes (FR-006.7, AT4, IC-1).** Each row of ``ERROR_CODES_RELIED_ON`` is confirmed in the
  sibling's OWN interpreter: its harness (``error_code_harnesses/``) imports the sibling's code from
  a ``git archive`` of the commit miAssist's snapshot of that app is pinned at, reaches the raise
  site with stubs, and prints the ``[code, status]`` pairs it raised. Nothing is searched for as
  text. A harness that cannot reach its site fails; there is no silent skip.
- **Copies (FR-006.1, FR-006.2).** Each ``vendored`` app's copy equals the sibling's file at
  ``origin/main`` and at the commit its ``docs/schemas/README.md`` row names, byte for byte.

Skips loudly when a sibling is absent; fails under ``MIASSIST_REQUIRE_CROSS_REPO_CHECKS=1`` or
``MISTUDIO_REQUIRE_CROSS_REPO_CHECKS=1``.
"""

from __future__ import annotations

import json
import os
import subprocess
from functools import cache
from pathlib import Path

import pytest
from scripts import snapshot_openapi as snap

from tests.support import answer_contracts as ac
from tests.support import response_shapes as rs
from tests.support import siblings
from tests.support.error_codes import ERROR_CODES_RELIED_ON, ReliedCode

pytestmark = pytest.mark.cross_repo

HARNESSES = Path(__file__).resolve().parent / "error_code_harnesses"
SIBLING = {
    "miworkbench": siblings.MIWORKBENCH,
    "miserver": siblings.MISERVER,
    "midataworks": siblings.MIDATAWORKS,
    "miforge": siblings.MIFORGE,
}


@cache
def _tree(app: str) -> tuple[Path, Path, str]:
    root = siblings.require_root(SIBLING[app], f"{app}'s error codes cannot be confirmed")
    commit = str(rs.snapshot(app)["commit"])
    tree, _ = snap.export(snap.RECIPES[app]["folder"], commit, repo=root)
    return tree / snap.RECIPES[app]["cwd"], snap.interpreter(app, root), commit


@cache
def raised(harness: str) -> tuple[list[list[object]], str]:
    app = harness.split("_", 1)[0]
    cwd, python, commit = _tree(app)
    scratch = cwd / ".harness-data"
    scratch.mkdir(exist_ok=True)
    env = {
        **os.environ,
        **snap.IMPORT_ENV,
        "DATA_DIR": str(scratch),
        "HF_HOME": str(scratch / "hf"),
        "HF_CACHE_DIR": str(scratch / "hf"),
    }
    done = subprocess.run(
        [str(python), "-I", "-B", str(HARNESSES / harness), str(cwd)],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    lines = done.stdout.strip().splitlines()
    assert (
        done.returncode == 0 and lines
    ), f"{harness} could not reach its raise site in {app} at {commit}: {done.stderr[-2500:]}"
    found: list[list[object]] = json.loads(lines[-1])
    return found, commit


@pytest.mark.parametrize("row", ERROR_CODES_RELIED_ON, ids=lambda r: f"{r.app}-{r.code}-{r.status}")
def test_each_relied_on_code_is_the_siblings_own(row: ReliedCode) -> None:
    found, commit = raised(row.harness)
    codes = {str(code) for code, _ in found}
    assert row.code in codes, f"{row.app} at {commit} raises {sorted(codes)}, not {row.code!r}"
    if row.where != "result.code":  # a job's result records the error; the job read is a 200
        statuses = {int(str(status)) for code, status in found if code == row.code}
        assert row.status in statuses, f"{row.app} at {commit}: {row.code} is {sorted(statuses)}"


def _vendored() -> list[str]:
    return [app for app in ac.APPS if ac.vendored(app)]


def published(app: str, ref: str) -> bytes:
    root = siblings.require_root(SIBLING[app], f"{ac.FILES[app]} cannot be compared")
    shown = subprocess.run(
        ["git", "-C", str(root), "show", f"{ref}:docs/schemas/{ac.FILES[app]}"],
        capture_output=True,
        check=False,
    )
    assert shown.returncode == 0, f"{app} has no docs/schemas/{ac.FILES[app]} at {ref}"
    return shown.stdout


def revision(raw: bytes) -> object:
    return json.loads(raw).get("revision")


@pytest.mark.parametrize("app", _vendored())
def test_each_copy_is_the_producers_file_at_origin_main(app: str) -> None:
    """FR-006.1 AC: a producer's later revision (additive or not) turns this red until re-vendored
    (NC2), naming both revisions."""
    mine, theirs = ac.path(app).read_bytes(), published(app, "origin/main")
    assert mine == theirs, (
        f"{ac.FILES[app]} (revision {revision(mine)}) differs from {app}'s origin/main (revision "
        f"{revision(theirs)}): copy it again, never edit it"
    )


@pytest.mark.parametrize("app", _vendored())
def test_each_copy_is_the_file_at_its_readme_commit(app: str) -> None:
    """FR-006.1 AC: the copy is the file at the commit its README row names."""
    commit, rev = ac.copied(ac.readme_row(ac.FILES[app]))
    assert ac.path(app).read_bytes() == published(app, commit), f"{app} at {commit}"
    assert revision(ac.path(app).read_bytes()) == rev
