"""004 after review round 3 (review-int-r3, 2026-11-16): a version is bound to its dataset
(OR3-int-6), the source and status lines no test pinned (OR3-int-5: SW07, SW08), and the default
next steps' reasons (OR3-int-7)."""

from __future__ import annotations

from typing import Any

import pytest

from tests.playbooks.dataset.fake import Dataworks, writes
from tests.playbooks.dataset.support import Session, data
from tests.playbooks.dataset.test_status import built, status_of

REPO = "evalfx-org/published"


# -- R3 review fix (OR3-int-6): another dataset's version id ------------------------------------


@pytest.mark.parametrize("tool", ["check", "publish"])
async def test_a_version_of_another_dataset_is_not_found(tool: str) -> None:
    """The reviewer's probe (``test_r3_foreign_version.py``): ``dataset: alpha`` with beta's
    version id used to file a hub_push for beta's version."""
    dw_ = Dataworks()
    dw_.seed_built("alpha")
    beta = dw_.seed_built("beta")
    args: dict[str, Any] = {"dataset": "alpha", "version": beta["version"]["id"]}
    if tool == "publish":
        args |= {"repo_id": REPO, "confirm": True}
    async with Session(dw_) as s:
        result = await s.call(f"miassist_dataset_{tool}", args)
    assert result.is_error and "version_not_built" in str(result.content), result
    assert writes(s.app) == []


async def test_the_publish_summary_names_the_dataset() -> None:
    dw_ = Dataworks()
    name = dw_.seed_built("alpha")["dataset"]["name"]
    async with Session(dw_) as s:
        result = await s.call(
            "miassist_dataset_publish", {"dataset": name, "repo_id": REPO, "confirm": True}
        )
    summary = result.structured_content["approval"]["summary"]
    assert summary.startswith("Publish version 1 of dataset alpha to evalfx-org/published as")


# -- R3 review fix (OR3-int-5): SW07, SW08 -----------------------------------------------------


@pytest.mark.parametrize("state", ["importing", "failed"])
async def test_a_source_that_is_not_ready_is_never_adopted(state: str) -> None:
    dw_ = Dataworks()
    source = dw_._source("evalfx-org/half-imported")
    source["display_name"] = "my-upload"
    source["state"] = state
    async with Session(dw_) as s:
        result = await s.call("miassist_dataset_build", {"source": "my-upload"})
    assert result.is_error and "source_not_found" in str(result.content), result
    assert writes(s.app) == []


async def test_status_reads_an_executed_publish_without_its_row() -> None:
    dw_, name = built(publish_status=None)
    version = next(iter(dw_.versions.values()))
    dw_._approve_later(
        "hub_push",
        {"body": {"version_id": version["id"], "repo_id": "a/b", "visibility": "private"}},
    )
    dw_.decide("executed", row=False)
    got = await status_of(dw_, name)
    assert got["where"] == "publish", got


# -- R3 review fix (OR3-int-7): each default next step says what it does ------------------------


async def test_the_default_next_steps_say_what_each_step_does() -> None:
    dw_ = Dataworks()
    name = dw_.seed_built()["dataset"]["name"]
    async with Session(dw_) as s:
        got = await s.call("miassist_dataset_check", {"dataset": name})
    steps = got.structured_content["next_steps"]
    publish = [x for x in steps if x["tool"] == "miassist_dataset_publish"]
    assert publish and publish[0]["why"] == (
        "Publish the version; its approval re-runs every check first."
    ), steps
    assert data(got)["state"] == "awaiting_publish_checks"
