"""``derive``: the dataset playbook's state from facts (004 FTDD §7; FTID §7). Pure.

Checked from the end backwards (state 14 to 1): the furthest state the facts support wins. The
facts come from a snapshot of miDataworks (``snapshot.read``) and, inside a tool call, from what the
call itself just learned (an import refused for size, a plan that labels rows, a job's status).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final

#: Publish statuses (``models/publish.py:57-70``).
PUBLISHED: Final = frozenset({"published", "no_change"})
PUBLISHING: Final = frozenset({"queued", "checking", "uploading", "verifying", "running"})
PUBLISH_FAILED: Final = frozenset({"refused", "verification_failed", "failed", "cancelled"})
#: Job statuses.
JOB_DONE: Final = frozenset({"succeeded", "completed", "complete", "done", "finished"})
JOB_FAILED: Final = frozenset({"failed", "cancelled", "canceled", "error"})

#: Each state, its step, and the tool a person calls next (``None``: wait or the operator).
STATES: Final[dict[str, tuple[str, str | None]]] = {
    "nothing_chosen": ("find", "miassist_dataset_find"),
    "source_chosen": ("build", "miassist_dataset_build"),
    "awaiting_import": ("build", None),
    "importing": ("build", None),
    "imported": ("build", "miassist_dataset_build"),
    "dataset_no_recipe": ("build", "miassist_dataset_build"),
    "recipe_saved": ("build", "miassist_dataset_build"),
    "awaiting_operator_build": ("build", None),
    "build_waiting": ("build", None),
    "building": ("build", None),
    "build_empty": ("build", None),
    "build_failed": ("build", None),
    "version_ready": ("check", "miassist_dataset_check"),
    "checking": ("check", None),
    "awaiting_publish_checks": ("check", "miassist_dataset_publish"),
    "checked": ("publish", "miassist_dataset_publish"),
    "publish_waiting": ("publish", None),
    "publishing": ("publish", None),
    "published": ("publish", None),
    "rejected": ("publish", "miassist_dataset_publish"),
    "expired": ("publish", "miassist_dataset_publish"),
    "failed": ("publish", "miassist_dataset_publish"),
}


@dataclass(frozen=True)
class Facts:
    """What is known about one dataset's journey. ``None`` means unknown or absent."""

    source_named: bool = False
    import_handoff: str | None = None  # "private" or "large"
    import_job: str | None = None  # the import job's status
    source_ready: bool = False
    dataset: bool = False
    recipe_saved: bool = False
    plan_labels: int | None = None
    build_approval: str | None = None  # an approval status for POST /versions (A19)
    build_job: str | None = None
    version_state: str | None = None
    version_rows: int | None = None
    files_status: str | None = None
    check_run_status: str | None = None
    approval_status: str | None = None  # the hub_push approval's A6 status
    publish_status: str | None = None


def _done(status: str | None) -> bool:
    return status is not None and status.lower() in JOB_DONE


def _failed(status: str | None) -> bool:
    return status is not None and status.lower() in JOB_FAILED


def derive(f: Facts) -> str:
    """The state (FTDD §7), from the end backwards."""
    # 14, 13 and the publish failures
    if f.publish_status in PUBLISHED:
        return "published"
    if f.publish_status in PUBLISH_FAILED:
        return "failed"
    if f.publish_status in PUBLISHING:
        return "publishing"
    if f.approval_status in ("rejected", "expired", "failed"):
        return str(f.approval_status)
    if f.approval_status in ("executing", "executed", "approved"):
        return "publishing"
    # 12
    if f.approval_status == "pending":
        return "publish_waiting"
    # 11, 10
    if f.version_state is not None and (f.version_rows or 0) > 0:
        if f.check_run_status is not None:
            return "checked" if _done(f.check_run_status) else "checking"
        if f.files_status is not None and not _done(f.files_status):
            return "checking"
        if f.files_status is not None:
            return "awaiting_publish_checks"
        return "version_ready"
    # 8
    if f.version_state is not None:
        return "build_failed" if _failed(f.version_state) else "build_empty"
    if _failed(f.build_job):
        return "build_failed"
    # 7, 6a, 6
    if f.build_job is not None:
        return "building"
    if f.build_approval == "pending":
        return "build_waiting"
    if f.plan_labels is not None:
        return "awaiting_operator_build"
    if f.recipe_saved:
        return "recipe_saved"
    # 5, 4
    if f.dataset:
        return "dataset_no_recipe"
    if f.source_ready:
        return "imported"
    # 3
    if f.import_handoff is not None:
        return "awaiting_import"
    if f.import_job is not None and not _done(f.import_job):
        return "importing"
    # 2, 1
    if f.source_named:
        return "source_chosen"
    return "nothing_chosen"


def current_publish(
    publishes: Sequence[Mapping[str, Any]], approval: Mapping[str, Any] | None
) -> Mapping[str, Any] | None:
    """The publish that tells this journey's state (R1 review fix OR1-pb-11, 2026-11-16).

    With an approval, only the publish row its executor created (``PublishOut.approval_id``,
    ``schemas/publishing.py:128`` at 58087b1) or a publish started AFTER it counts: while the
    approval executes and before its row exists, an OLDER (e.g. failed) publish of the same
    version is not this one, so the state stays ``publishing`` and no second filing is offered.
    Without an approval, the newest publish."""
    ordered = sorted(publishes, key=lambda p: str(p.get("created_at") or ""), reverse=True)
    if approval is None:
        return ordered[0] if ordered else None
    for publish in ordered:
        if approval.get("id") is not None and publish.get("approval_id") == approval.get("id"):
            return publish
    since = str(approval.get("created_at") or "")
    newer = [p for p in ordered if since and str(p.get("created_at") or "") > since]
    return newer[0] if newer else None


def step_of(state: str) -> str:
    return STATES[state][0]


def next_tool(state: str) -> str | None:
    return STATES[state][1]


def as_int(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None
