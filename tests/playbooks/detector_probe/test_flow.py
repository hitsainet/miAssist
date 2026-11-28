"""``flow.derive`` by table: every state of FTDD §7 and the approval outcomes (FTASKS 2.2)."""

from __future__ import annotations

from typing import Any

import pytest

from miassist.playbooks.detector_probe.flow import StepState as S
from miassist.playbooks.detector_probe.flow import derive
from miassist.playbooks.detector_probe.snapshot import Snapshot

W, D, SV = "miworkbench", "midataworks", "miserver"
ALL = frozenset({W, D, SV})
VIEWS = {
    r: {"id": f"v-{r}"} for r in ("train", "test", "calibration", "everyday_text", "nonsense_text")
}
REPORT = {
    "probe": {"rung": 2},
    "evaluations": [{"dataset_id": f"v-{r}"} for r in ("test", "everyday_text", "nonsense_text")],
}


def snap(**kw: Any) -> Snapshot:
    return Snapshot(key="k", behaviour={"key": "k"}, **kw)


def ap(status: str, **kw: Any) -> dict[str, Any]:
    return {"id": "a1", "status": status, **kw}


CASES: list[tuple[str, Snapshot, dict[str, Any], S, str]] = [
    ("undescribed", Snapshot(key="k"), {}, S.UNDESCRIBED, "describe"),
    ("described", snap(), {}, S.DESCRIBED, "data"),
    ("awaiting_download", snap(), {"awaiting_download": True}, S.AWAITING_DOWNLOAD, "data"),
    ("dataset_downloading", snap(), {"downloading": True}, S.DATASET_DOWNLOADING, "data"),
    ("labels_unmapped", snap(), {"unmapped": ["maybe"]}, S.LABELS_UNMAPPED, "data"),
    ("views_partial", snap(views={"train": {"id": "v"}}), {}, S.VIEWS_PARTIAL, "data"),
    ("dw_journey_step", snap(dw_status={"next_step": "rule_set"}), {}, S.DW_JOURNEY_STEP, "data"),
    (
        "dw_send_waiting",
        snap(dw_status={"next_step": "send"}, approvals={"send": ap("pending")}),
        {},
        S.DW_SEND_WAITING,
        "data",
    ),
    (
        "dw_send_running",
        snap(dw_status={}, dw_send={"state": "running"}),
        {},
        S.DW_SEND_RUNNING,
        "data",
    ),
    (
        "data_checked",
        snap(dw_status={"complete": True}, dw_send={"state": "completed"}),
        {},
        S.DATA_CHECKED,
        "data",
    ),
    ("views_ready", snap(views=dict(VIEWS)), {}, S.VIEWS_READY, "train"),
    (
        "train_waiting",
        snap(views=dict(VIEWS), approvals={"training": ap("pending")}),
        {},
        S.TRAIN_WAITING,
        "train",
    ),
    (
        "train_approved",
        snap(views=dict(VIEWS), approvals={"training": ap("approved")}),
        {},
        S.TRAIN_APPROVED,
        "train",
    ),
    ("training", snap(views=dict(VIEWS), run={"status": "running"}), {}, S.TRAINING, "train"),
    (
        "trained",
        snap(views=dict(VIEWS), run={"status": "completed", "selection": {"selected": "p"}}),
        {},
        S.TRAINED,
        "verdict",
    ),
    (
        "verdict_waiting",
        snap(
            views=dict(VIEWS),
            run={"status": "completed", "selection": {"selected": "p"}},
            approvals={"evaluation": ap("pending")},
        ),
        {},
        S.VERDICT_WAITING,
        "verdict",
    ),
    (
        "evaluating",
        snap(views=dict(VIEWS), run={"status": "completed", "selection": {"selected": "p"}}),
        {"evaluation_task": "t"},
        S.EVALUATING,
        "verdict",
    ),
    (
        "judged",
        snap(views=dict(VIEWS), run={"status": "completed"}, report=REPORT),
        {},
        S.JUDGED,
        "deploy",
    ),
    (
        "deploy_waiting",
        snap(views=dict(VIEWS), report=REPORT, approvals={"definition": ap("pending")}),
        {},
        S.DEPLOY_WAITING,
        "deploy",
    ),
    (
        "deploy_building",
        snap(views=dict(VIEWS), report=REPORT),
        {"definition_task": "t"},
        S.DEPLOY_BUILDING,
        "deploy",
    ),
    ("awaiting_hub_import", snap(), {"hub_repo": "evalfx/probe"}, S.AWAITING_HUB_IMPORT, "deploy"),
    ("awaiting_arm", snap(sv_probe={"id": "sp"}), {}, S.AWAITING_ARM, "deploy"),
    ("watching", snap(sv_probe={"id": "sp"}, sv_armed=True), {}, S.WATCHING, "deploy"),
    (
        "rejected",
        snap(views=dict(VIEWS), approvals={"training": ap("denied", decision_reason="no")}),
        {},
        S.REJECTED,
        "train",
    ),
    (
        "expired",
        snap(
            views=dict(VIEWS),
            approvals={"evaluation": ap("expired")},
            run={"status": "completed", "selection": {"selected": "p"}},
        ),
        {},
        S.EXPIRED,
        "verdict",
    ),
    (
        "failed-after-consume",
        snap(views=dict(VIEWS), approvals={"definition": ap("failed", reason="x")}, report=REPORT),
        {},
        S.FAILED,
        "deploy",
    ),
    (
        "failed-in-worker",
        snap(
            views=dict(VIEWS),
            approvals={"training": ap("consumed")},
            run={"status": "failed", "error_message": "out of memory"},
        ),
        {},
        S.FAILED,
        "train",
    ),
    ("failed-send", snap(dw_status={}, approvals={"send": ap("failed")}), {}, S.FAILED, "data"),
]


@pytest.mark.parametrize("case", CASES, ids=[c[0] for c in CASES])
def test_state_table(case: tuple[str, Snapshot, dict[str, Any], S, str]) -> None:
    _, snapshot, chosen, state, step = case
    derived = derive(snapshot, ALL, chosen)
    assert (derived.state, derived.step) == (state, step)


def test_every_state_is_in_the_table() -> None:
    assert {c[3] for c in CASES} >= set(S) - {S.VERDICT_APPROVED, S.DEPLOY_APPROVED}


def test_failed_run_carries_its_reason() -> None:
    derived = derive(
        snap(views=dict(VIEWS), run={"status": "failed", "error_message": "oom"}), ALL, {}
    )
    assert derived.state is S.FAILED and derived.detail == {"reason": "oom"}
