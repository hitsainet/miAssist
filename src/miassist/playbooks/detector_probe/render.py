"""Results of the five tools, built by Core's result builder (001 FR-12; FPRD §4).

Every word comes from ``guidance/playbooks/detector-probe.yaml`` (the state texts) through the
explain files' slots; app names of sets, models and datasets appear only in ``data`` (FPRD §4.5).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from mcp.types import CallToolResult

from miassist.errors import MiAssistError
from miassist.playbooks.detector_probe.context import PLAYBOOK, Ctx
from miassist.playbooks.detector_probe.flow import TOOL_OF, Derived
from miassist.results.build import build
from miassist.tools.core import tool_error


def next_for(derived: Derived, key: str, ctx: Ctx) -> list[dict[str, Any]]:
    tool = TOOL_OF[derived.step]
    if derived.state.value in ("watching", "data_checked") or tool_name_absent(ctx, derived.step):
        return [
            {
                "tool": "miassist_status",
                "args": {"playbook": PLAYBOOK, "subject": key},
                "why": ctx.say(f"state.{derived.state.value}.next"),
            }
        ]
    args: dict[str, Any] = {"key": key}
    if derived.state.value in ("rejected", "expired", "failed"):
        args["ask_again"] = True
    return [{"tool": tool, "args": args, "why": ctx.say(f"state.{derived.state.value}.next")}]


def tool_name_absent(ctx: Ctx, step: str) -> bool:
    needs = {"train": "miworkbench", "verdict": "miworkbench", "deploy": "miserver"}.get(step)
    return needs is not None and not ctx.has(needs)


def result(
    ctx: Ctx,
    tool: str,
    derived: Derived,
    key: str,
    *,
    data: Mapping[str, Any] | None = None,
    approval: Mapping[str, Any] | None = None,
    next_steps: Sequence[Mapping[str, Any]] | None = None,
    state_text: str | None = None,
    summary: str | None = None,
    what: str | None = None,
) -> CallToolResult:
    name = state_text or derived.state.value
    body: dict[str, Any] = {
        "playbook": PLAYBOOK,
        "subject": key,
        "step": derived.step,
        "state": derived.state.value,
        "summary": summary or ctx.say(f"state.{name}.what"),
        "waiting": [],
        **dict(data or {}),
    }
    slots = {
        "what": what or ctx.say(f"state.{name}.what"),
        "why": ctx.say(f"state.{name}.why"),
        "good": ctx.say(f"state.{name}.good"),
        "next": ctx.say(f"state.{name}.next"),
    }
    return build(
        ctx.guidance,
        tool=tool,
        outcome="state",
        level=ctx.level,
        data=body,
        next_steps=list(next_steps) if next_steps is not None else next_for(derived, key, ctx),
        approval=approval,
        slots=slots,
    )


def unavailable(ctx: Ctx, tool: str, app: str, reason: str, key: str) -> CallToolResult:
    return build(
        ctx.guidance,
        tool=tool,
        outcome="unavailable",
        level=ctx.level,
        data=None,
        unavailable=app,
        reason=reason,
        slots={"app_name": ctx.guidance.app_name(app)},
        next_steps=[
            {
                "tool": "miassist_status",
                "args": {"playbook": PLAYBOOK, "subject": key},
                "why": ctx.guidance.why("app_back"),
            }
        ],
    )


def error(ctx: Ctx, err: MiAssistError) -> CallToolResult:
    return tool_error(ctx.deps, err)
