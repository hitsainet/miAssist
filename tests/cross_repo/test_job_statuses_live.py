"""miAssist's job-status sets are miDataworks' own (2026-11-25 fix; ENH-013 FR-006.10, BR-SA05).

``JOB_DONE``, ``JOB_FAILED`` and ``JOB_RUNNING`` (``playbooks/dataset/flow.py``) must partition the
``status`` miDataworks writes on a job. The values are read in miDataworks' OWN interpreter from a
``git archive`` of the commit miAssist's miDataworks snapshot is pinned at (nothing is written in
the sibling), never from a list typed here:

- ``models/job.py``: ``JOB_STATUSES`` (the CHECK constraint on ``dw_jobs.status``) and
  ``TERMINAL_STATUSES``;
- ``core/cancellation.py``: ``plan_cancel``, what a cancel request does to a ``queued`` job (ends
  it) and to a ``running`` one (``cancelling``: stops at its next checkpoint, still live).

Skips loudly when miDataworks is absent; fails under ``MIASSIST_REQUIRE_CROSS_REPO_CHECKS=1`` or
``MISTUDIO_REQUIRE_CROSS_REPO_CHECKS=1``.
"""

from __future__ import annotations

import json
import os
import subprocess
from functools import cache
from typing import Any

import pytest
from scripts import snapshot_openapi as snap

from miassist.playbooks.dataset.flow import JOB_DONE, JOB_FAILED, JOB_RUNNING
from tests.support import response_shapes as rs
from tests.support import siblings

pytestmark = pytest.mark.cross_repo

READ = r"""
import json, sys
sys.path.insert(0, ".")
from src.models.job import JOB_STATUSES, TERMINAL_STATUSES
from src.core.cancellation import plan_cancel
sys.stdout.write("\n@@JOBS@@" + json.dumps({
    "statuses": list(JOB_STATUSES),
    "terminal": sorted(TERMINAL_STATUSES),
    "cancel": {s: plan_cancel(s).new_status for s in JOB_STATUSES},
}))
"""


@cache
def _midataworks() -> dict[str, Any]:
    root = siblings.require_root(
        siblings.MIDATAWORKS, "miAssist's job-status sets cannot be checked against miDataworks'"
    )
    commit = rs.snapshot("midataworks")["commit"]
    tree, _ = snap.export(snap.RECIPES["midataworks"]["folder"], commit, repo=root)
    done = subprocess.run(
        [str(snap.interpreter("midataworks", root)), "-B", "-c", READ],
        cwd=tree / snap.RECIPES["midataworks"]["cwd"],
        env={**os.environ, **snap.IMPORT_ENV, "DATA_DIR": str(tree / ".jobs-data")},
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert "@@JOBS@@" in done.stdout, f"miDataworks at {commit}: {done.stderr[-2000:]}"
    found: dict[str, Any] = json.loads(done.stdout.split("@@JOBS@@", 1)[1])
    found["commit"] = commit
    return found


def test_the_sets_partition_midataworks_job_statuses() -> None:
    dw = _midataworks()
    statuses, terminal = set(dw["statuses"]), set(dw["terminal"])
    assert len(statuses) == len(dw["statuses"]) and terminal <= statuses
    assert not (JOB_DONE & JOB_FAILED or JOB_DONE & JOB_RUNNING or JOB_FAILED & JOB_RUNNING)
    assert JOB_DONE | JOB_FAILED | JOB_RUNNING == statuses, (
        f"miDataworks at {dw['commit']} sends {sorted(statuses)}; miAssist names "
        f"{sorted(JOB_DONE | JOB_FAILED | JOB_RUNNING)}"
    )
    assert JOB_DONE | JOB_FAILED == terminal, "the ends are miDataworks' terminal statuses"
    assert JOB_RUNNING == statuses - terminal, "everything else is still waited on"


def test_a_cancel_ends_as_failed_or_is_still_waited_on() -> None:
    """A cancel that ends a job (a queued one) ends it in ``JOB_FAILED``, never ``JOB_DONE``; one
    that asks a running job to stop leaves it in ``JOB_RUNNING`` (``cancelling``), so miAssist
    keeps waiting until the job reaches a terminal status."""
    cancel = _midataworks()["cancel"]
    assert cancel["queued"] in JOB_FAILED
    assert cancel["running"] in JOB_RUNNING and cancel["running"] not in ("running", None)
    assert cancel[cancel["running"]] is None, "a second cancel changes nothing"
