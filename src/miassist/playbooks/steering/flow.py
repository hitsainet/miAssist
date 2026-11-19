"""``derive``: the steering playbook's state from facts (005 FTDD §7; FTID §7). Pure; from the
end backwards (11 to 1)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

TASK_RUNNING: Final = frozenset({"pending", "started", "progress", "queued", "running"})
TASK_FAILED: Final = frozenset({"failure", "revoked", "failed"})

#: state -> (step, the tool a person calls next or None for a wait / the operator)
STATES: Final[dict[str, tuple[str, str | None]]] = {
    "nothing_found": ("find", "miassist_steering_find"),
    "feature_chosen": ("try", "miassist_steering_try"),
    "sweep_waiting": ("try", None),
    "sweep_approved": ("try", "miassist_steering_try"),
    "sweeping": ("try", None),
    "swept": ("save", "miassist_steering_save"),
    "combined_waiting": ("save", None),
    "combining": ("save", None),
    "saved": ("serve", "miassist_steering_serve"),
    "model_load_waiting": ("serve", None),
    "awaiting_hub_import": ("serve", None),
    "imported": ("serve", "miassist_steering_serve"),
    "awaiting_activation": ("serve", None),
    "active": ("serve", None),
    "rejected": ("try", "miassist_steering_try"),
    "expired": ("try", "miassist_steering_try"),
    "failed": ("try", "miassist_steering_try"),
}


@dataclass(frozen=True)
class Facts:
    feature: bool = False
    sweep_approval: str | None = None  # A6 status of the steer_sweep request
    sweep_task: str | None = None
    combined_approval: str | None = None
    combined_task: str | None = None
    profile: bool = False
    hub_pending: bool = False
    model_load: str | None = None  # A6 status of the model_load request
    imported: bool = False
    trial_done: bool = False
    active: bool = False


def derive(f: Facts) -> str:
    if f.active:
        return "active"
    if f.imported and f.trial_done:
        return "awaiting_activation"
    if f.model_load == "pending":
        return "model_load_waiting"
    if f.imported:
        return "imported"
    if f.hub_pending:
        return "awaiting_hub_import"
    if f.profile:
        return "saved"
    for approval, task, waiting, running in (
        (f.combined_approval, f.combined_task, "combined_waiting", "combining"),
        (f.sweep_approval, f.sweep_task, "sweep_waiting", "sweeping"),
    ):
        if task is not None:
            if task in TASK_FAILED:
                return "failed"
            if task in TASK_RUNNING:
                return running
            return "swept"
        if approval in ("rejected", "expired", "failed"):
            return str(approval)
        if approval == "pending":
            return waiting
        if approval == "approved":
            return "sweep_approved" if running == "sweeping" else waiting
    if f.feature:
        return "feature_chosen"
    return "nothing_found"


def step_of(state: str) -> str:
    return STATES[state][0]


def next_tool(state: str) -> str | None:
    return STATES[state][1]
