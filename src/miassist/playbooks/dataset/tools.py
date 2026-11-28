"""The four ``miassist_dataset_*`` tools (004 FTDD §5; FPRD FR-004.6 - FR-004.9; A26).

All four are write tools with ``destructiveHint: false`` (A13, A23: even the find starts Hub search
and preview jobs in miDataworks' worker). No argument accepts a token (FR-004.18). The level changes
only ``explain`` (FR-004.20). An unreachable miDataworks is answered ``unavailable`` with no request
(FR-004.5).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Annotated, Any, Literal

from mcp.server.mcpserver import Context
from mcp.types import CallToolResult
from pydantic import Field

from miassist.errors import MiAssistError
from miassist.playbooks import ask as asking
from miassist.playbooks.dataset import actions
from miassist.playbooks.dataset.actions import BuildArgs, Ctx, Outcome, PublishArgs
from miassist.playbooks.dataset.flow import next_tool, step_of
from miassist.playbooks.dataset.recipe import DATASET_NAME_PATTERN
from miassist.playbooks.dataset.snapshot import Down
from miassist.results.build import build
from miassist.server.specs import Deps, Effect, ToolSpec
from miassist.tools.core import Result, key_hash_of, level_for, request_key, tool_error

APP = "midataworks"
PLAYBOOK = "dataset"
#: miDataworks' publish ``REPO_ID_PATTERN`` (``schemas/publishing.py:15``).
REPO_ID = r"^[A-Za-z0-9][A-Za-z0-9._-]{0,95}/[A-Za-z0-9][A-Za-z0-9._-]{0,95}$"
SLOT_DEFAULTS = {"detail": "-", "reason": "-", "number": "-", "rows": "-", "repo_id": "-"}
CHOSEN = ("source_id", "dataset_id", "version_id", "build_id", "repo_id", "visibility")

ToolFn = Callable[..., Awaitable[CallToolResult]]
#: The reason for each default next step (R3 review fix OR3-int-7).
WHY = {
    "miassist_dataset_build": "next.build",
    "miassist_dataset_check": "next.check",
    "miassist_dataset_publish": "next.publish",
}


def summary(ctx: Ctx, out: Outcome) -> str:
    text = ctx.w(f"state.{out.state}", **{**SLOT_DEFAULTS, **out.slots})
    lines = out.fields.get("summary_lines") or []
    return "\n".join([text, *lines]) if lines else text


def default_next(ctx: Ctx, out: Outcome, subject: str | None) -> list[dict[str, Any]]:
    if out.next_steps:
        return out.next_steps
    tool = next_tool(out.state)
    ref = out.fields.get("dataset_name") or subject
    if out.state == "published":
        return []
    if tool is None or not ref:
        return (
            [
                actions.step(
                    "miassist_status",
                    {"playbook": PLAYBOOK, "subject": ref or ""},
                    ctx.w("end.status"),
                )
            ]
            if ref
            else []
        )
    # R3 review fix (OR3-int-7), 2026-11-16: the reason says what the offered step does, not
    # "see where this dataset stands" for every tool.
    why = WHY.get(tool, "end.status")
    return [
        actions.step(
            tool,
            {"dataset": ref} if tool != "miassist_dataset_build" else {"source": ref},
            ctx.w(why),
        )
    ]


async def finish(
    ctx: Ctx, tool: str, out: Outcome, key_hash: str | None, subject: str | None = None
) -> CallToolResult:
    subject = out.subject or subject
    data = {
        "playbook": PLAYBOOK,
        "subject": subject,
        "step": step_of(out.state),
        "state": out.state,
        "summary": summary(ctx, out),
        "waiting": out.waiting,
        **{k: v for k, v in out.fields.items() if k != "summary_lines"},
    }
    next_steps = default_next(ctx, out, subject)
    if out.state == "published":
        data["honest_end"] = ctx.w("end.done")
        if "miworkbench" in ctx.deps.runtime.installed:
            next_steps = [
                actions.step("miassist_guide", {"topic": "playbooks"}, ctx.w("end.detector"))
            ]
    if key_hash and subject:
        chosen = {k: data.get(k) for k in CHOSEN if data.get(k) is not None}
        await ctx.deps.runtime.store.save_progress(
            key_hash, PLAYBOOK, subject, 1, {"chosen": chosen}
        )
    return build(
        ctx.deps.guidance,
        tool=tool,
        outcome=out.state,
        level=ctx.level,
        data=data,
        next_steps=next_steps,
        approval=out.approval,
        terms=("dataset-version",),
    )


def unavailable(ctx: Ctx, tool: str, reason: str) -> CallToolResult:
    return build(
        ctx.deps.guidance,
        tool=tool,
        outcome="unavailable",
        level=ctx.level,
        data=None,
        unavailable=APP,
        reason=reason,
        next_steps=[actions.step("miassist_status", {}, ctx.deps.guidance.why("app_back"))],
    )


async def run(
    deps: Deps,
    ctx_: Context[Any, Any] | None,
    tool: str,
    body: Callable[[Ctx], Awaitable[Outcome | CallToolResult | Any]],
) -> CallToolResult:
    key_hash = key_hash_of(request_key(ctx_))
    ctx = Ctx(deps, deps.runtime.clients[APP], await level_for(deps, key_hash))
    reason = deps.runtime.detector.unreachable_reason(APP)
    if reason is not None:
        return unavailable(ctx, tool, reason)
    try:
        out = await body(ctx)
    except Down as down:
        return unavailable(ctx, tool, down.reason)
    except MiAssistError as error:
        return tool_error(deps, error)
    if not isinstance(out, Outcome):
        return out  # a form or the teaching result of ask()
    return await finish(ctx, tool, out, key_hash)


Query = Annotated[str, Field(min_length=1, max_length=200)]
Limit = Annotated[int, Field(ge=1, le=10)]
Name = Annotated[str, Field(pattern=DATASET_NAME_PATTERN.pattern, max_length=100)]
Short = Annotated[str, Field(min_length=1, max_length=255)]
RepoId = Annotated[str, Field(pattern=REPO_ID, max_length=193)]


def make_find(deps: Deps) -> ToolFn:
    async def miassist_dataset_find(
        ctx: Context[Any, Any],
        query: Query,
        licence: Literal["any", "open", "redistributable"] = "any",
        limit: Limit = 5,
    ) -> Result:
        return await run(
            deps,
            ctx,
            "miassist_dataset_find",
            lambda c: actions.converge_find(c, query, licence, limit),
        )

    return miassist_dataset_find


def make_build(deps: Deps) -> ToolFn:
    async def miassist_dataset_build(
        ctx: Context[Any, Any],
        source: Short,
        config: Short | None = None,
        split: Short | None = None,
        revision: Short | None = None,
        name: Name | None = None,
        text_column: Short | None = None,
        label_column: Short | None = None,
        recipe: dict[str, Any] | None = None,
    ) -> Result:
        args = BuildArgs(source, config, split, revision, name, text_column, label_column, recipe)
        return await run(
            deps, ctx, "miassist_dataset_build", lambda c: actions.converge_build(c, args)
        )

    return miassist_dataset_build


def make_check(deps: Deps) -> ToolFn:
    async def miassist_dataset_check(
        ctx: Context[Any, Any],
        dataset: Short,
        version: Short | None = None,
        check_run_id: Short | None = None,
    ) -> Result:
        return await run(
            deps,
            ctx,
            "miassist_dataset_check",
            lambda c: actions.converge_check(c, dataset, version, check_run_id),
        )

    return miassist_dataset_check


def make_publish(deps: Deps) -> ToolFn:
    async def miassist_dataset_publish(
        ctx: Context[Any, Any],
        dataset: Short,
        repo_id: RepoId,
        version: Short | None = None,
        visibility: Literal["private", "public"] = "private",
        card_prose: Annotated[str, Field(max_length=100_000)] | None = None,
        ask_again: bool = False,
        confirm: bool = False,
    ) -> Result:
        args = PublishArgs(dataset, repo_id, version, visibility, card_prose, ask_again)

        async def gate(c: Ctx) -> Any:
            """The visibility form before the one filing (no write happens before it)."""
            if confirm:
                return None
            call = {
                "dataset": dataset,
                "repo_id": repo_id,
                "visibility": visibility,
                "confirm": True,
                **({"version": version} if version else {}),
                **({"ask_again": True} if ask_again else {}),
            }
            choice = asking.Choice(
                name="visibility",
                title=c.w("publish.choose_visibility"),
                options=("private", "public"),
                recommended=visibility,
                reason=c.w("reason.private"),
            )
            answer = await asking.ask(
                ctx,
                c.deps.guidance,
                tool="miassist_dataset_publish",
                args=call,
                choices=[choice],
                level=c.level,
            )
            if isinstance(answer, asking.Answered):
                args.visibility = answer.values["visibility"]
                return None
            return answer

        return await run(
            deps, ctx, "miassist_dataset_publish", lambda c: actions.converge_publish(c, args, gate)
        )

    return miassist_dataset_publish


EFFECTS: frozenset[Effect] = frozenset({"store_read", "store_write", "app_read", "app_write"})
SPECS: tuple[ToolSpec, ...] = (
    ToolSpec("miassist_dataset_find", frozenset({APP}), False, False, EFFECTS, make_find),
    ToolSpec("miassist_dataset_build", frozenset({APP}), False, False, EFFECTS, make_build),
    ToolSpec("miassist_dataset_check", frozenset({APP}), False, False, EFFECTS, make_check),
    ToolSpec("miassist_dataset_publish", frozenset({APP}), False, False, EFFECTS, make_publish),
)
