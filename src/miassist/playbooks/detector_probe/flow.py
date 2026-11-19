"""The journey's state, derived from a snapshot (003 FTDD §7, FTID §7). Pure: no I/O.

``derive`` checks the states from the END backwards (watching first), so a person who did steps
outside miAssist is placed correctly. Approval outcomes (rejected, expired, failed) are reported
against the step whose approval it was.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from miassist.playbooks.detector_probe.snapshot import Snapshot, selected_probe

#: The five roles own data registers (FPRD FR-003.9); ``ood`` is optional.
REQUIRED_ROLES = ("train", "test", "calibration", "everyday_text", "nonsense_text")
AUTHORING_STEPS = frozenset(
    {
        "rule_set",
        "templates",
        "recipe",
        "plan",
        "generation",
        "build",
        "second_opinion",
        "agreement",
        "review",
        "sets",
        "check",
    }
)


class StepState(StrEnum):
    UNDESCRIBED = "undescribed"
    DESCRIBED = "described"
    AWAITING_DOWNLOAD = "awaiting_download"
    DATASET_DOWNLOADING = "dataset_downloading"
    LABELS_UNMAPPED = "labels_unmapped"
    VIEWS_PARTIAL = "views_partial"
    DW_JOURNEY_STEP = "dw_journey_step"
    DW_SEND_WAITING = "dw_send_waiting"
    DW_SEND_RUNNING = "dw_send_running"
    DATA_CHECKED = "data_checked"
    VIEWS_READY = "views_ready"
    TRAIN_WAITING = "train_waiting"
    TRAIN_APPROVED = "train_approved"
    TRAINING = "training"
    TRAINED = "trained"
    VERDICT_WAITING = "verdict_waiting"
    VERDICT_APPROVED = "verdict_approved"
    EVALUATING = "evaluating"
    JUDGED = "judged"
    DEPLOY_WAITING = "deploy_waiting"
    DEPLOY_APPROVED = "deploy_approved"
    DEPLOY_BUILDING = "deploy_building"
    AWAITING_HUB_IMPORT = "awaiting_hub_import"
    AWAITING_ARM = "awaiting_arm"
    WATCHING = "watching"
    REJECTED = "rejected"
    EXPIRED = "expired"
    FAILED = "failed"


S = StepState
STEP_OF: dict[StepState, str] = {
    S.UNDESCRIBED: "describe",
    S.DESCRIBED: "data",
    S.AWAITING_DOWNLOAD: "data",
    S.DATASET_DOWNLOADING: "data",
    S.LABELS_UNMAPPED: "data",
    S.VIEWS_PARTIAL: "data",
    S.DW_JOURNEY_STEP: "data",
    S.DW_SEND_WAITING: "data",
    S.DW_SEND_RUNNING: "data",
    S.DATA_CHECKED: "data",
    S.VIEWS_READY: "train",
    S.TRAIN_WAITING: "train",
    S.TRAIN_APPROVED: "train",
    S.TRAINING: "train",
    S.TRAINED: "verdict",
    S.VERDICT_WAITING: "verdict",
    S.VERDICT_APPROVED: "verdict",
    S.EVALUATING: "verdict",
    S.JUDGED: "deploy",
    S.DEPLOY_WAITING: "deploy",
    S.DEPLOY_APPROVED: "deploy",
    S.DEPLOY_BUILDING: "deploy",
    S.AWAITING_HUB_IMPORT: "deploy",
    S.AWAITING_ARM: "deploy",
    S.WATCHING: "deploy",
}
TOOL_OF = {
    "describe": "miassist_detector_start",
    "data": "miassist_detector_data",
    "train": "miassist_detector_train",
    "verdict": "miassist_detector_verdict",
    "deploy": "miassist_detector_deploy",
}
KIND_STEP = {"training": "train", "evaluation": "verdict", "definition": "deploy", "send": "data"}
#: An approval's app status (miWorkbench's or miDataworks') read as a journey outcome.
OUTCOME = {"denied": S.REJECTED, "rejected": S.REJECTED, "expired": S.EXPIRED, "failed": S.FAILED}
RUN_ACTIVE = frozenset({"queued", "pending", "running", "started"})
RUN_FAILED = frozenset({"failed", "error", "cancelled"})
#: A miDataworks detector send that ended without its views (``models/detector_send.py:36-44``).
SEND_ENDED = frozenset({"failed", "cancelled", "rejected"})


@dataclass(frozen=True)
class Derived:
    state: StepState
    step: str
    kind: str | None = None
    detail: Mapping[str, Any] | None = None


def _approval(snap: Snapshot, kind: str) -> str | None:
    found = snap.approvals.get(kind)
    return str(found.get("status")) if found else None


def _approval_state(snap: Snapshot, kind: str, waiting: S, approved: S) -> Derived | None:
    status = _approval(snap, kind)
    step = KIND_STEP[kind]
    if status in ("pending", "pending_approval", "executing"):
        return Derived(waiting if status != "executing" else approved, step, kind)
    if status == "approved":
        return Derived(approved, step, kind)
    if status in OUTCOME:
        return Derived(OUTCOME[status], step, kind, snap.approvals[kind])
    return None


def evaluated_everywhere(snap: Snapshot) -> bool:
    """The report has a rung and an evaluation on every registered evaluation-type view."""
    report = snap.report or {}
    probe = report.get("probe") if isinstance(report.get("probe"), Mapping) else None
    if probe is None or not isinstance(probe.get("rung"), int):
        return False
    done = {e.get("dataset_id") for e in report.get("evaluations") or [] if isinstance(e, Mapping)}
    needed = {
        v.get("id")
        for role, v in snap.views.items()
        if role in ("test", "ood", "everyday_text", "nonsense_text")
    }
    return bool(needed) and needed <= done


def views_ready(snap: Snapshot) -> bool:
    return all(role in snap.views for role in REQUIRED_ROLES)


def derive(snap: Snapshot, installed: frozenset[str], chosen: Mapping[str, Any]) -> Derived:
    if snap.sv_armed:
        return Derived(S.WATCHING, "deploy")
    if snap.sv_probe is not None:
        return Derived(S.AWAITING_ARM, "deploy")
    if chosen.get("hub_repo"):
        return Derived(S.AWAITING_HUB_IMPORT, "deploy")
    if "miworkbench" in installed:
        found = _workbench_state(snap, chosen)
        if found is not None:
            return found
    if "midataworks" in installed:
        found = _dataworks_state(snap, chosen, "miworkbench" in installed)
        if found is not None:
            return found
    if snap.behaviour is not None:
        return Derived(S.DESCRIBED, "data")
    return Derived(S.UNDESCRIBED, "describe")


def _workbench_state(snap: Snapshot, chosen: Mapping[str, Any]) -> Derived | None:
    found = _approval_state(snap, "definition", S.DEPLOY_WAITING, S.DEPLOY_APPROVED)
    if found is not None:
        return found
    if chosen.get("definition_task") and not chosen.get("miserver_probe_id"):
        return Derived(S.DEPLOY_BUILDING, "deploy")
    if evaluated_everywhere(snap) and _approval(snap, "evaluation") not in ("approved", "pending"):
        return Derived(S.JUDGED, "deploy")
    found = _approval_state(snap, "evaluation", S.VERDICT_WAITING, S.VERDICT_APPROVED)
    if found is not None:
        return found
    if chosen.get("evaluation_task"):
        return Derived(S.EVALUATING, "verdict")
    run = snap.run or {}
    status = str(run.get("status") or "")
    if status == "completed" and (snap.report is not None or selected_probe(run)):
        return Derived(S.TRAINED, "verdict")
    if status in RUN_FAILED:
        reason = run.get("error_message") or status
        return Derived(S.FAILED, "train", "training", {"reason": str(reason)[:300]})
    if status in RUN_ACTIVE or (status and status != "completed"):
        return Derived(S.TRAINING, "train")
    found = _approval_state(snap, "training", S.TRAIN_WAITING, S.TRAIN_APPROVED)
    if found is not None:
        return found
    if views_ready(snap):
        return Derived(S.VIEWS_READY, "train")
    if chosen.get("awaiting_download") and not snap.views:
        return Derived(S.AWAITING_DOWNLOAD, "data")
    if chosen.get("downloading") and not snap.views:
        return Derived(S.DATASET_DOWNLOADING, "data")
    if chosen.get("unmapped"):
        return Derived(S.LABELS_UNMAPPED, "data")
    if snap.views:
        return Derived(S.VIEWS_PARTIAL, "data")
    return None


def _dataworks_state(snap: Snapshot, chosen: Mapping[str, Any], workbench: bool) -> Derived | None:
    if chosen.get("route") != "build_with_midataworks" and snap.dw_status is None:
        return None
    found = _approval_state(snap, "send", S.DW_SEND_WAITING, S.DW_SEND_RUNNING)
    send = snap.dw_send or {}
    if send.get("state") == "completed":
        return Derived(S.DATA_CHECKED, "data")
    # R1 review fix (OR1-pb-13), 2026-11-16: miDataworks' terminal send states
    # (``models/detector_send.py:36-44``); it never emits "refused".
    if send.get("state") in SEND_ENDED:
        return Derived(S.FAILED, "data", "send", {"reason": str(send.get("state"))})
    if send.get("state"):
        return Derived(S.DW_SEND_RUNNING, "data")
    if found is not None:
        if found.state is S.DW_SEND_RUNNING and _approval(snap, "send") != "executing":
            return Derived(S.DW_SEND_RUNNING, "data", "send")
        return found
    status = snap.dw_status or {}
    next_step = status.get("next_step")
    # R3 review fix (OR3-int-3), 2026-11-16 (OVN-miassist-int-28): miDataworks marks ``check`` done
    # only when a send exists (``journey.py``: "a send of the behaviour's sets records its
    # checks"), and the send runs the checks before any approval is filed (``send_service.prepare``:
    # ``send_allowed`` or ``send_refused``). So with live sets and no send yet, the send is next:
    # the checks run, and miDataworks files the send only when they pass.
    if next_step == "check" and status.get("set_ids"):
        next_step = "send"
    if next_step in AUTHORING_STEPS or next_step == "resolve":
        return Derived(S.DW_JOURNEY_STEP, "data", detail={"step": next_step})
    if next_step == "send":
        if not workbench:
            # The send registers views in the training app; without it the data is done here.
            return Derived(S.DATA_CHECKED, "data")
        return Derived(S.DW_JOURNEY_STEP, "data", detail={"step": "send"})
    if status.get("complete"):
        return Derived(S.DATA_CHECKED, "data")
    if isinstance(next_step, str) and next_step:
        # R3 review fix (OR3-int-5, SW10), 2026-11-16: a step a later miDataworks adds is still
        # the operator's step there, explained by the app's own title (quoted, bounded).
        return Derived(S.DW_JOURNEY_STEP, "data", detail={"step": next_step})
    return None
