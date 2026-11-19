"""The dataset playbook's status provider (004 FTDD §6 ``status.py``; FPRD FR-004.19, FR-004.19a).

Core dispatches ``miassist_status(playbook="dataset", subject=<dataset name or id>)`` here. The
status is derived from miDataworks alone (a snapshot of reads), never from the progress record, so
deleting the record changes nothing (FR-004.19). For each step it builds that step tool's ``data``
from the snapshot and calls Core's ``evaluate_done_when`` exactly once (FR-004.19a): there is no
second copy of the predicate here.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from miassist.errors import MiAssistError
from miassist.playbooks.dataset import flow
from miassist.playbooks.dataset.flow import Facts, as_int, current_publish, derive
from miassist.playbooks.dataset.snapshot import DatasetSnapshot, Down, read
from miassist.playbooks.done_when import evaluate_done_when
from miassist.playbooks.registry import ResolvedPlaybook
from miassist.results.approvals import approval_object

if TYPE_CHECKING:
    from miassist.server.specs import Deps

APP = "midataworks"


def step_data(snap: DatasetSnapshot) -> dict[str, dict[str, Any]]:
    """Each step tool's ``data`` fields, as the tool would report them, from the snapshot."""
    version = snap.version or {}
    rows = as_int(version.get("total_rows")) or 0
    publish = current_publish(snap.publishes, snap.approval)
    publish_status = publish.get("status") if publish else None
    approval_status = (snap.approval or {}).get("status")
    candidate = None
    if snap.dataset is not None:
        candidate = {"repo_id": snap.dataset.get("name"), "dataset_id": snap.dataset.get("id")}
    return {
        "find": {"candidates": [candidate] if candidate else []},
        "build": {"version_ready": bool(snap.version) and rows > 0},
        # The publish the operator approves re-runs every check (publishing.py:132): a publish
        # of this version, or an approval that ran, means a completed check run exists.
        "check": {
            "checks_complete": bool(snap.publishes) or approval_status in ("executing", "executed")
        },
        "publish": {"publish_status": publish_status},
    }


def facts(snap: DatasetSnapshot) -> Facts:
    version = snap.version or {}
    publish = current_publish(snap.publishes, snap.approval)
    return Facts(
        dataset=snap.dataset is not None,
        version_state=str(version.get("state") or "ready") if snap.version else None,
        version_rows=as_int(version.get("total_rows")),
        approval_status=(snap.approval or {}).get("status"),
        publish_status=publish.get("status") if publish else None,
    )


class DatasetStatusProvider:
    """Live progress of one dataset (by name or id); keeps no state."""

    async def __call__(
        self, deps: Deps, playbook: ResolvedPlaybook, key_hash: str | None, subject: str
    ) -> dict[str, Any]:
        words = deps.guidance.playbooks["dataset"].texts

        def w(key: str, **slots: Any) -> str:
            return deps.guidance.render(words[key], slots).text

        snap = DatasetSnapshot()
        expected_override = None
        if subject:
            try:
                snap = await read(deps.runtime.clients[APP], subject)
            except Down:
                expected_override = w("status.unavailable")
            except MiAssistError:
                expected_override = w("status.unreadable")
        data = step_data(snap)
        done: list[str] = []
        first_open = None
        for step in playbook.runnable:
            if evaluate_done_when(step.done_when, data.get(step.id)):
                done.append(step.id)
            elif first_open is None:
                first_open = step
        state = derive(facts(snap))
        waiting: list[dict[str, Any]] = []
        approval = snap.approval
        if approval is not None and state in ("publish_waiting", "publishing"):
            mapped = approval_object(
                APP,
                approval,
                style="server_executed",
                summary=w("wait.approval", approval_id=approval.get("id")),
            )
            if state == "publish_waiting":
                waiting.append(
                    {"kind": "approval", "detail": mapped["summary"], "approval": mapped}
                )
        if state == "publishing":
            waiting.append({"kind": "job", "detail": w("state.publishing")})
        if state == "version_ready":
            waiting.append({"kind": "operator_action", "detail": w("wait.run_checks")})
        finished = first_open is None
        nxt = None
        if first_open is not None and not waiting:
            ref = (snap.dataset or {}).get("name") or subject
            args = (
                {"source": ref} if first_open.tool == "miassist_dataset_build" else {"dataset": ref}
            )
            if first_open.tool == "miassist_dataset_find" or not ref:
                args = {"query": ref} if ref else {}
            nxt = {"tool": first_open.tool, "args": args, "why": first_open.explain_expert}
        version = snap.version or {}
        slots = {
            "detail": "-",
            "reason": (approval or {}).get("reason") or "-",
            "number": version.get("number", "-"),
            "rows": version.get("total_rows", "-"),
            "repo_id": (current_publish(snap.publishes, snap.approval) or {}).get("repo_id", "-"),
        }
        expected = expected_override or w(f"state.{state}", **slots)
        return {
            "playbook_id": playbook.id,
            "playbook_version": playbook.version,
            "finished": finished,
            "where": first_open.id if first_open else None,
            "done": done,
            "next": nxt,
            "waiting": waiting,
            "expected": expected,
            "not_in_this_installation": playbook.not_in_this_installation,
        }


PROVIDER = DatasetStatusProvider()
_ = flow  # the state table lives in flow; this module only reads it through derive
