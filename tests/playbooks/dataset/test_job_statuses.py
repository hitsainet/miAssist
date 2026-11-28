"""Each job status miDataworks sends takes its documented branch (2026-11-25 fix; ENH-013 FR-006.10).

``JOB_DONE``, ``JOB_FAILED`` and ``JOB_RUNNING`` (``playbooks/dataset/flow.py``) partition
miDataworks' job ``status``; ``tests/cross_repo/test_job_statuses_live.py`` reads miDataworks' own
values and pins the partition. Here every value of the three sets runs through the dataset
playbook's build and import against the fake miDataworks:

- ``completed``: finished, the version (or source) is read;
- ``failed``, ``cancelled``: terminal, a teaching error;
- ``queued``, ``running``, ``cancelling``: still waited on. The job is read again until the poll
  window ends, then the playbook answers ``building`` (``importing``) with a job wait naming the
  status. ``cancelling`` is miDataworks' "the operator asked it to stop; it stops at its next
  checkpoint" (``core/cancellation.py``): the job has not ended, so it is not finished and not yet
  failed.

The six values the old sets guessed (``GUESSED``) are none of miDataworks' and are no longer read
as an end; the vendored job answer's enum refuses them in a fake.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from miassist.playbooks.dataset.flow import JOB_DONE, JOB_FAILED, JOB_RUNNING
from tests.playbooks.dataset.fake import PUBLIC, Dataworks
from tests.playbooks.dataset.support import Session, data
from tests.support import response_shapes as rs

JOB = "/api/v1/jobs/{job_id}"
ALL = sorted(JOB_DONE | JOB_FAILED | JOB_RUNNING)
#: The values the sets held before 2026-11-25 that miDataworks never sends (``models/job.py``).
GUESSED = ("succeeded", "complete", "done", "finished", "canceled", "error")


@dataclass
class Statused(Dataworks):
    """The fake miDataworks with the build job (``import_status``: the import job) in ``status``."""

    build_status: str = "completed"
    import_status: str = "completed"

    def _job(
        self, result: dict[str, Any], status: str = "completed", error: str | None = None
    ) -> str:
        if "version_id" in result:
            status = self.build_status
        elif "source_id" in result:
            status = self.import_status
        if status in JOB_FAILED:
            error = error or f"the job is {status}"
        return super()._job(result, status, error)


async def _build(world: Statused) -> tuple[Session, Any]:
    async with Session(world) as s:
        result = await s.call("miassist_dataset_build", {"source": PUBLIC})
    return s, result


def test_the_three_sets_are_disjoint() -> None:
    assert not (JOB_DONE & JOB_FAILED or JOB_DONE & JOB_RUNNING or JOB_FAILED & JOB_RUNNING)


@pytest.mark.parametrize("status", ALL)
async def test_a_build_job_in_each_status_takes_its_branch(status: str) -> None:
    s, result = await _build(Statused(build_status=status))
    reads = len(s.log("GET", JOB))
    if status in JOB_DONE:
        got = data(result)
        assert got["state"] == "version_ready" and reads == 2  # the import's read, the build's
    elif status in JOB_FAILED:
        assert result.is_error and result.content[0].text.startswith("build_failed:")
        assert f"the job is {status}" in result.content[0].text and reads == 2
    else:
        got = data(result)
        assert got["state"] == "building", got
        assert got["waiting"][0]["kind"] == "job" and status in got["waiting"][0]["detail"]
        assert reads > 2, "an unfinished job is read again until the window ends"


@pytest.mark.parametrize("status", ALL)
async def test_an_import_job_in_each_status_takes_its_branch(status: str) -> None:
    s, result = await _build(Statused(import_status=status))
    reads = len(s.log("GET", JOB))
    if status in JOB_DONE:
        assert data(result)["state"] == "version_ready"
    elif status in JOB_FAILED:
        assert result.is_error and result.content[0].text.startswith("import_failed:")
        assert reads == 1 and s.log("POST", "/api/v1/datasets") == []
    else:
        got = data(result)
        assert got["state"] == "importing", got
        assert got["waiting"][0]["kind"] == "job" and status in got["waiting"][0]["detail"]
        assert reads > 1 and s.log("POST", "/api/v1/datasets") == []


async def test_cancelling_is_waited_on_not_finished() -> None:
    """FR-006.10's named case: the operator asked the build to stop; it has not stopped yet."""
    assert "cancelling" in JOB_RUNNING
    s, result = await _build(Statused(build_status="cancelling"))
    got = data(result)
    assert got["state"] == "building" and "cancelling" in got["waiting"][0]["detail"]
    assert not result.is_error and len(s.log("GET", JOB)) > 2


async def test_a_cancelled_job_is_an_end_but_never_a_success() -> None:
    """``cancelled`` is terminal (the poll stops) and is not ``completed``: a cancelled build made
    no version miAssist may read, so it is ``build_failed``, never ``version_ready``."""
    assert "cancelled" in JOB_FAILED and "cancelled" not in JOB_DONE | JOB_RUNNING
    s, result = await _build(Statused(build_status="cancelled"))
    assert result.is_error and result.content[0].text.startswith("build_failed:")
    assert len(s.log("GET", JOB)) == 2


def test_the_sets_are_the_vendored_job_status_enum() -> None:
    """The default suite's pin: the union equals the ``status`` enum of the vendored job answer,
    which ``scripts/snapshot_shapes.py`` overlays from miDataworks' ``JOB_STATUSES`` and
    ``tests/cross_repo/test_response_shapes_live.py`` regenerates from the code. (The cross-repo
    ``test_job_statuses_live.py`` reads miDataworks itself, terminal statuses and cancel included.)
    A value outside it, such as the six guessed before, is an answer the fake cannot give."""
    job = rs.schema_for("midataworks", "GET", JOB, 200)
    assert set(job["properties"]["status"]["enum"]) == JOB_DONE | JOB_FAILED | JOB_RUNNING
    assert not set(GUESSED) & (JOB_DONE | JOB_FAILED | JOB_RUNNING)
