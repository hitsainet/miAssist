"""The detector-probe StatusProvider (003 FPRD FR-003.24 - FR-003.26; FTDD §6; 001 AC-23.3).

Status is DERIVED from the apps by the key (FR-003.25): the snapshot, then ``flow.derive``; the
progress record only adds ids the person chose. Each step's completion is Core's
``evaluate_done_when`` over the step tool's ``data`` built from the snapshot, called once per step
(FR-003.25a); this module never re-derives completion itself.
"""

from __future__ import annotations

from typing import Any

from miassist.playbooks import done_when as core_done_when
from miassist.playbooks._shared.calm import quote
from miassist.playbooks.detector_probe import flow, snapshot
from miassist.playbooks.detector_probe.context import Ctx
from miassist.playbooks.detector_probe.flow import Derived, StepState
from miassist.playbooks.registry import ResolvedPlaybook
from miassist.server.specs import Deps

S = StepState
GPU = frozenset({S.TRAINING, S.EVALUATING})
JOB = frozenset({S.DATASET_DOWNLOADING, S.DW_SEND_RUNNING, S.DEPLOY_BUILDING})
OPERATOR = {
    S.AWAITING_DOWNLOAD: "handoff.download",
    S.AWAITING_ARM: "handoff.arm",
    S.AWAITING_HUB_IMPORT: "handoff.hub_import",
    S.DW_JOURNEY_STEP: "handoff.dw_step",
}
APPROVAL = frozenset({S.TRAIN_WAITING, S.VERDICT_WAITING, S.DEPLOY_WAITING, S.DW_SEND_WAITING})


def step_data(snap: snapshot.Snapshot, derived: Derived) -> dict[str, dict[str, Any]]:
    """Each step tool's ``data`` as the snapshot shows it (the fields ``done_when`` reads)."""
    report = snap.report or {}
    found = report.get("probe")
    probe: dict[str, Any] = found if isinstance(found, dict) else {}
    run_done = str((snap.run or {}).get("status") or "") == "completed"
    out: dict[str, dict[str, Any]] = {
        "describe": {"key": snap.key} if snap.behaviour is not None else {},
        "data": {
            "data_ready": flow.views_ready(snap) or derived.state is S.DATA_CHECKED,
        },
        "train": {"trained": run_done},
        "verdict": ({"rung": probe.get("rung")} if flow.evaluated_everywhere(snap) else {}),
        "deploy": {"armed": snap.sv_armed},
    }
    return out


def waiting(ctx: Ctx, snap: snapshot.Snapshot, derived: Derived) -> list[dict[str, Any]]:
    state = derived.state
    detail = ctx.say(f"state.{state.value}.what")
    if state in APPROVAL and derived.kind in snap.approvals:
        from miassist.results.approvals import approval_object

        app = "midataworks" if derived.kind == "send" else "miworkbench"
        style = "server_executed" if app == "midataworks" else "file_first"
        approval = approval_object(
            app,
            snap.approvals[derived.kind],
            style=style,  # type: ignore[arg-type]
            summary=ctx.say(f"approval.{derived.kind}.what"),
        )
        return [{"kind": "approval", "detail": detail, "approval": approval}]
    if state in GPU:
        return [{"kind": "gpu", "detail": detail}]
    if state in JOB:
        return [{"kind": "job", "detail": detail}]
    if state in OPERATOR:
        return [{"kind": "operator_action", "detail": ctx.say(OPERATOR[state])}]
    return []


class DetectorStatus:
    async def __call__(
        self, deps: Deps, playbook: ResolvedPlaybook, key_hash: str | None, subject: str
    ) -> dict[str, Any]:
        ctx = Ctx(deps, None, key_hash, "beginner")
        await ctx.load(subject)
        snap = await snapshot.read(ctx, subject) if subject else snapshot.Snapshot(key="")
        derived = flow.derive(snap, ctx.installed, ctx.chosen)
        datas = step_data(snap, derived)
        done = [
            step.id
            for step in playbook.runnable
            if core_done_when.evaluate_done_when(step.done_when, datas[step.id])
        ]
        runnable = [s.id for s in playbook.runnable]
        finished = derived.state is S.WATCHING or (
            bool(runnable) and all(s in done for s in runnable)
        )
        current = None if finished else derived.step
        if current is not None and current not in runnable:
            current = next((s for s in runnable if s not in done), None)
            finished = current is None
        nxt = None
        if current is not None:
            step = next(s for s in playbook.runnable if s.id == current)
            nxt = {
                "tool": step.tool,
                "args": {"key": subject} if subject else {},
                "why": ctx.say(f"state.{derived.state.value}.next"),
            }
        expected = ctx.say(f"state.{derived.state.value}.good")
        if derived.state is S.WATCHING:
            counts = {"fired": "0", "not_fired": "0", "not_scored": "0"}
            counts.update(snap.sv_event_counts or {})
            expected = ctx.say("state.watching.counts", **counts)
            if snap.sv_paused_reason:
                expected += " " + ctx.say(
                    "state.watching.paused", reason=quote(snap.sv_paused_reason)
                )
        return {
            "playbook_id": playbook.id,
            "playbook_version": playbook.version,
            "finished": finished,
            "where": current,
            "done": done,
            "next": nxt,
            "waiting": [] if finished else waiting(ctx, snap, derived),
            "expected": expected,
            "not_in_this_installation": playbook.not_in_this_installation,
        }


PROVIDER = DetectorStatus()
