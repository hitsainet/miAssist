"""FR-002.12: the full reference agrees with 001's route snapshots on every route both hold (two
sources, not one); cross-repo, against each sibling (skips loudly; fails under the switch)."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from miassist_eval import openapi_ref
from tests.support import harness

REPO = Path(__file__).resolve().parents[3]


@pytest.mark.parametrize("app", openapi_ref.APPS)
def test_reference_agrees_with_cores_snapshot(app: str) -> None:
    snap_path = openapi_ref.snapshot_dir() / f"{app}.json"
    if not snap_path.is_file():
        pytest.skip(f"LOUD SKIP: Core's snapshot {snap_path} is absent")
    snap = json.loads(snap_path.read_text())
    assert snap["paths"], "the snapshot holds no route; the comparison would be empty"
    assert openapi_ref.agrees_with_snapshot(harness.refs()[app], snap) == []


@pytest.mark.parametrize("app", openapi_ref.APPS)
def test_a_code_reference_holds_the_same_routes_as_cores_index(app: str) -> None:
    """A provisional (``code:``) reference is generated from the same commit as Core's full route
    index, so the two hold the same routes (018 re-pin, control F2: a reference left at the old
    commit, missing two new miForge routes, passed every other eval test; the route profiles are
    derived from it). A ``live:`` reference is FTASKS 1.5's and may be of another commit."""
    ref = harness.refs()[app]
    if not ref.source.startswith("code:"):
        pytest.skip(f"LOUD SKIP: {app}'s reference is {ref.source}, not generated from code")
    index = json.loads((openapi_ref.snapshot_dir() / f"{app}.index.json").read_text())
    assert ref.source == f"code:{app}@{index['commit']}", (
        f"{app}'s reference ({ref.source}) and Core's route index ({index['commit']}) are of "
        "different commits; refresh: eval/scripts/write_reference.py app=REF"
    )
    assert {(r.method, r.template) for r in ref.routes} == {
        (row["method"], row["path"]) for row in index["routes"]
    }


def test_the_comparison_sees_a_difference() -> None:
    snap = json.loads((openapi_ref.snapshot_dir() / "midataworks.json").read_text())
    path = next(iter(snap["paths"]))
    method = next(iter(snap["paths"][path]))
    snap["paths"][path][method].setdefault("responses", {})["200"] = {
        "content": {"application/json": {"schema": {"type": "integer"}}}
    }
    assert openapi_ref.agrees_with_snapshot(harness.refs()["midataworks"], snap)


SIBLINGS = {
    "miworkbench": ("MIWORKBENCH_REPO", "miWorkbench"),
    "miserver": ("MISERVER_REPO", "miServer"),
    "midataworks": ("MIDATAWORKS_REPO", "miDataworks"),
    "miforge": ("MIFORGE_REPO", "miForge"),
}


@pytest.mark.parametrize("app", openapi_ref.APPS)
def test_cross_repo_the_reference_commit_exists_in_the_sibling(app: str) -> None:
    """The provisional reference names the sibling commit it was generated from; that commit must
    exist in the sibling checkout (the live comparison is FTASKS 1.5's)."""
    var, folder = SIBLINGS[app]
    root = Path(os.environ.get(var, REPO.parent / folder))
    required = (
        os.environ.get("MIASSIST_REQUIRE_CROSS_REPO_CHECKS") == "1"
        or os.environ.get("MISTUDIO_REQUIRE_CROSS_REPO_CHECKS") == "1"
    )
    if not (root / ".git").exists():
        if required:
            pytest.fail(f"sibling {folder} absent at {root}")
        pytest.skip(f"LOUD SKIP: sibling {folder} absent at {root}")
    source = harness.refs()[app].source
    assert source.startswith(("code:", "live:")), source
    if source.startswith("code:"):
        import subprocess

        sha = source.rsplit("@", 1)[1]
        ok = subprocess.run(
            ["git", "-C", str(root), "cat-file", "-e", f"{sha}^{{commit}}"],
            capture_output=True,
            check=False,
        )
        assert ok.returncode == 0, f"{folder} has no commit {sha}"
