"""Check and publish against a fake miDataworks, on the request log (004 FTASKS 4.1-4.4, 5.1-5.4,
6.3; FPRD FR-004.5, FR-004.8, FR-004.9, FR-004.13 - FR-004.16, FR-004.18)."""

from __future__ import annotations

import json
from typing import Any

import pytest

from tests.playbooks.dataset.fake import Dataworks, writes
from tests.playbooks.dataset.support import Session, data

REPO = "evalfx-org/published"
TOOLS = ("find", "build", "check", "publish")


def built(**kw: Any) -> tuple[Dataworks, str]:
    dw_ = Dataworks(**kw)
    return dw_, dw_.seed_built()["dataset"]["name"]


def run_of(*outcomes: tuple[str, str], status: str = "completed") -> dict[str, Any]:
    return {
        "id": "evalfx-run-1",
        "status": status,
        "results": [
            {
                "check": c,
                "outcome": o,
                "reason": f"{c} {o}",
                "next_step": "",
                "evidence": {"count": 7},
            }
            for c, o in outcomes
        ],
    }


ALL_GREEN = tuple((f"C-{n}", "green") for n in range(1, 10))

# -- check (4.x) --------------------------------------------------------------------------------


async def test_check_without_a_run_is_the_operators_step() -> None:
    dw_, name = built(
        leakage_pairs=14, shortcut_warnings=[{"column": "channel", "figure": 0.93, "chance": 0.5}]
    )
    async with Session(dw_) as s:
        got = data(await s.call("miassist_dataset_check", {"dataset": name}))
    assert got["state"] == "awaiting_publish_checks" and got["checks_complete"] is False
    assert got["waiting"] == [{"kind": "operator_action", "detail": got["waiting"][0]["detail"]}]
    assert "Versions, Publish" in got["waiting"][0]["detail"]
    by = {c["id"]: c for c in got["checks"]}
    assert by["C-3"]["outcome"] == "amber" and "14" in by["C-3"]["evidence"]
    assert by["C-7"]["outcome"] == "amber" and "channel" in by["C-7"]["evidence"]
    assert by["C-1"]["outcome"] == "not_run"
    assert "not run yet (counts as amber)" in got["summary"]
    assert "ready to publish" not in json.dumps(got).lower()
    assert "published privately now" not in got["summary"]
    assert got["publish_checks"] == "operator"
    # never runs the checks or the leakage check (A34)
    assert s.log("POST", "/api/v1/versions/{version_id}/publish-checks") == []
    assert all(not (r.method == "POST" and r.path.endswith("/leakage")) for r in s.app.requests)
    assert writes(s.app) == [("POST", "/api/v1/versions/{version_id}/publish-builds")]


async def test_check_with_the_operators_run_explains_every_check() -> None:
    outcomes = (*ALL_GREEN[:6], ("C-7", "amber"), *ALL_GREEN[7:])
    dw_, name = built(check_run=run_of(*outcomes))
    async with Session(dw_) as s:
        result = await s.call(
            "miassist_dataset_check", {"dataset": name, "check_run_id": "evalfx-run-1"}
        )
    got = data(result)
    assert got["state"] == "checked" and got["checks_complete"] is True
    assert [c["id"] for c in got["checks"]] == [f"C-{n}" for n in range(1, 10)]
    assert got["publish_checks"]["push_allowed"] == {"private": True, "public": False}
    assert "It can be published privately now." in got["summary"]
    assert "Amber blocks a public push only." in got["summary"]
    assert any(line.startswith("C-7 amber") for line in got["summary"].splitlines())
    assert result.structured_content["next_steps"][0]["tool"] == "miassist_dataset_publish"


async def test_check_refused_c2_hands_the_token_to_the_operator() -> None:
    dw_, name = built(check_run=run_of(("C-2", "refused")))
    async with Session(dw_) as s:
        got = data(
            await s.call(
                "miassist_dataset_check", {"dataset": name, "check_run_id": "evalfx-run-1"}
            )
        )
    assert got["publish_checks"]["push_allowed"] == {"private": False, "public": False}
    assert any("Settings" in w["detail"] for w in got["waiting"] if w["kind"] == "operator_action")
    assert "published privately now" not in got["summary"]


async def test_check_of_a_running_run_is_checking() -> None:
    dw_, name = built(check_run=run_of(*ALL_GREEN, status="queued"))
    async with Session(dw_) as s:
        got = data(
            await s.call(
                "miassist_dataset_check", {"dataset": name, "check_run_id": "evalfx-run-1"}
            )
        )
    assert got["state"] == "checking" and got["waiting"][0]["kind"] == "job"
    assert got["checks_complete"] is False


async def test_check_of_an_unknown_dataset_is_a_teaching_error() -> None:
    async with Session(Dataworks()) as s:
        result = await s.call("miassist_dataset_check", {"dataset": "nope"})
    assert result.is_error and result.content[0].text.startswith("dataset_not_found:")


async def test_check_twice_builds_the_files_once() -> None:
    dw_, name = built()
    async with Session(dw_) as s:
        await s.call("miassist_dataset_check", {"dataset": name})
        await s.call("miassist_dataset_check", {"dataset": name})
    assert len(dw_.builds) == 1


# -- publish (5.x) ------------------------------------------------------------------------------


async def publish(s: Session, name: str, **args: Any) -> Any:
    return await s.call(
        "miassist_dataset_publish", {"dataset": name, "repo_id": REPO, "confirm": True, **args}
    )


async def test_publish_files_once_private_by_default_with_four_facts() -> None:
    dw_, name = built()
    async with Session(dw_) as s:
        result = await publish(s, name)
    got = data(result)
    posts = s.log("POST", "/api/v1/publishes")
    assert len(posts) == 1 and posts[0].body["visibility"] == "private"
    assert posts[0].body["repo_id"] == REPO and posts[0].body["build_id"]
    assert got["state"] == "publish_waiting"
    approval = result.structured_content["approval"]
    assert approval["decide_in"] == "midataworks" and approval["then"] == "server_runs"
    assert approval["status"] == "pending"
    summary = approval["summary"]
    for fact in (
        REPO,
        "PRIVATE",
        "What happens",
        "Cost",
        "Where",
        "Approvals",
        approval["id"],
        "Then",
    ):
        assert fact in summary, fact
    assert "3 files" in summary and "48000 rows" in summary
    for r in s.app.requests:
        assert r.headers["x-dataworks-agent"] == "agent:miassist"
        assert "approval" not in " ".join(r.headers).lower()
        assert approval["id"] not in json.dumps(r.body or {})


async def test_public_only_when_the_person_says_so() -> None:
    dw_, name = built()
    async with Session(dw_) as s:
        result = await publish(s, name, visibility="public")
    assert s.log("POST", "/api/v1/publishes")[0].body["visibility"] == "public"
    assert result.structured_content["approval"]["summary"].startswith(
        "Publish version 1 of dataset support-chats to evalfx-org/published as PUBLIC."
    )


async def test_without_confirm_the_teaching_result_writes_nothing() -> None:
    dw_, name = built()
    async with Session(dw_) as s:
        result = await s.call("miassist_dataset_publish", {"dataset": name, "repo_id": REPO})
    assert not result.is_error
    nxt = result.structured_content["next_steps"][0]
    assert nxt["tool"] == "miassist_dataset_publish" and nxt["args"]["confirm"] is True
    assert nxt["args"]["visibility"] == "private"
    assert writes(s.app) == []


async def test_repeat_call_finds_its_own_pending_row_and_sends_nothing() -> None:
    dw_, name = built()
    async with Session(dw_) as s:
        first = await publish(s, name)
        s.app.requests.clear()
        again = await publish(s, name)
    assert writes(s.app) == []
    assert again.structured_content["approval"]["id"] == first.structured_content["approval"]["id"]
    assert data(again)["state"] == "publish_waiting"


async def test_someone_elses_pending_row_is_not_ours() -> None:
    dw_, name = built()
    version = next(iter(dw_.versions.values()))
    other = dw_._approve_later(
        "hub_push",
        {"body": {"version_id": version["id"], "repo_id": REPO, "visibility": "private"}},
    )
    other["requested_by"] = "agent:someone"
    async with Session(dw_) as s:
        await publish(s, name)
    assert len(s.log("POST", "/api/v1/publishes")) == 1


@pytest.mark.parametrize("decision", ["rejected", "expired"])
async def test_rejected_or_expired_is_not_refiled_without_ask_again(decision: str) -> None:
    dw_, name = built()
    async with Session(dw_) as s:
        await publish(s, name)
        dw_.decide(decision, "not now")
        s.app.requests.clear()
        result = await publish(s, name)
        got = data(result)
        assert got["state"] == decision and writes(s.app) == []
        assert result.structured_content["next_steps"][0]["args"]["ask_again"] is True
        s.app.requests.clear()
        again = await publish(s, name, ask_again=True)
    assert data(again)["state"] == "publish_waiting"
    assert [w for w in writes(s.app) if w[1] == "/api/v1/publishes"] == [
        ("POST", "/api/v1/publishes")
    ]


async def test_executing_then_failed_publish_is_failed_with_a_next_step() -> None:
    dw_, name = built(publish_status="verification_failed")
    async with Session(dw_) as s:
        await publish(s, name)
        dw_.decide("executing")
        s.app.requests.clear()
        result = await publish(s, name)
    got = data(result)
    assert got["state"] == "failed" and result.structured_content["next_steps"]
    assert writes(s.app) == []


async def test_a_new_executing_publish_is_not_the_old_failed_one() -> None:
    """R1 review fix (OR1-pb-11), 2026-11-16: after a failed publish, ask_again files a second
    hub_push; while it executes and before its row exists, the old FAILED publish must not be
    read as this one: the state is publishing, nothing is offered again and nothing is filed."""
    dw_, name = built(publish_status="verification_failed")
    async with Session(dw_) as s:
        await publish(s, name)
        dw_.decide("executing")  # the first one runs and fails (row with its approval_id)
        dw_.approvals[-1]["status"] = "executed"  # the executor ran; its publish failed
        failed = data(await publish(s, name))
        assert failed["state"] == "failed"
        await publish(s, name, ask_again=True)
        assert len(s.log("POST", "/api/v1/publishes")) == 2
        dw_.decide("executing", row=False)  # approved, executing, no row yet
        s.app.requests.clear()
        result = await publish(s, name)
        status = await s.status(name)
    got = data(result)
    assert got["state"] == "publishing", got
    steps = result.structured_content["next_steps"]
    assert not any(st["args"].get("ask_again") for st in steps), steps
    assert writes(s.app) == []
    assert status["where"] == "publish" and status["waiting"][0]["kind"] == "job", status


@pytest.mark.parametrize("status", ["failed", "cancelled"])
@pytest.mark.parametrize("tool", ["check", "publish"])
async def test_a_failed_files_build_ends_instead_of_checking_forever(
    status: str, tool: str
) -> None:
    """R1 review fix (OR1-pb-13), 2026-11-16: miDataworks' BuildStatus has failed and cancelled
    (models/publish.py:42-47); either ends the step with what happened, never "checking"."""
    dw_, name = built(files_status=status)
    args = (
        {"dataset": name}
        if tool == "check"
        else {"dataset": name, "repo_id": REPO, "confirm": True}
    )
    async with Session(dw_) as s:
        result = await s.call(f"miassist_dataset_{tool}", args)
    assert result.is_error or result.structured_content.get("error"), result.content
    assert "could not build the files" in json.dumps(
        result.structured_content or [c.text for c in result.content]
    )
    assert s.log("POST", "/api/v1/publishes") == []


async def test_executed_and_published_is_the_honest_end() -> None:
    dw_, name = built(publish_status="published")
    async with Session(dw_) as s:
        await publish(s, name)
        dw_.decide("executed")
        result = await publish(s, name)
    got = data(result)
    assert got["state"] == "published" and got["honest_end"]
    assert result.structured_content["next_steps"] == []


async def test_with_miworkbench_the_end_points_at_the_detector_playbooks() -> None:
    dw_, name = built(publish_status="published")
    async with Session(dw_, installed=("miworkbench", "midataworks")) as s:
        await publish(s, name)
        dw_.decide("executed")
        result = await publish(s, name)
    steps = result.structured_content["next_steps"]
    assert steps and steps[0]["why"] == "Use this version for a detector."


# -- 6.3 down is unavailable --------------------------------------------------------------------

ARGS = {
    "find": {"query": "x"},
    "build": {"source": "evalfx-org/x"},
    "check": {"dataset": "x"},
    "publish": {"dataset": "x", "repo_id": REPO, "confirm": True},
}


@pytest.mark.parametrize("tool", TOOLS)
async def test_down_midataworks_is_unavailable_and_sent_nothing(tool: str) -> None:
    async with Session(Dataworks()) as s:
        s.deps.runtime.detector.mark_unreachable("midataworks", "connection refused")
        result = await s.call(f"miassist_dataset_{tool}", ARGS[tool])
    assert not result.is_error
    assert result.structured_content["unavailable"] == "midataworks"
    assert s.app.requests == []
