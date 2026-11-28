"""The four ``miassist_steering_*`` tools (005 FTDD §5; FPRD FR-005.6 - FR-005.10; A26).

``miassist_steering_find`` is read-only; try, save and serve are write tools with
``destructiveHint: false``. find, try and save need miWorkbench; serve needs miServer. No argument
accepts ``activate``, ``acknowledge_unvalidated`` or a token. The level changes only ``explain``.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Annotated, Any, Literal

from mcp.server.mcpserver import Context
from mcp.types import CallToolResult
from pydantic import Field

from miassist.errors import MiAssistError
from miassist.playbooks._shared.calm import honest_end_done as honest_end  # OVN-miassist-int-11
from miassist.playbooks.steering import actions
from miassist.playbooks.steering.actions import Ctx, Down, Outcome, SaveArgs, ServeArgs, TryArgs
from miassist.playbooks.steering.flow import next_tool, step_of
from miassist.results.build import build
from miassist.server.specs import Deps, Effect, ToolSpec
from miassist.tools.core import Result, key_hash_of, level_for, request_key, tool_error

PLAYBOOK = "steering"
SLOTS = {"name": "-"}
ToolFn = Callable[..., Awaitable[CallToolResult]]


def summary(ctx: Ctx, out: Outcome) -> str:
    text = ctx.w(f"state.{out.state}", **{**SLOTS, **out.slots})
    lines = out.fields.get("summary_lines") or []
    return "\n".join([text, *lines]) if lines else text


async def finish(ctx: Ctx, tool: str, out: Outcome, key_hash: str | None) -> CallToolResult:
    data: dict[str, Any] = {
        "playbook": PLAYBOOK,
        "subject": out.subject,
        "step": step_of(out.state),
        "state": out.state,
        "summary": summary(ctx, out),
        "waiting": out.waiting,
        **{k: v for k, v in out.fields.items() if k != "summary_lines"},
    }
    next_steps = list(out.next_steps)
    if out.state == "saved":
        if ctx.has("miserver"):
            ref = data.get("profile_id") or out.subject
            next_steps = next_steps or [
                actions.step("miassist_steering_serve", {"cluster": ref}, ctx.w("saved.serve"))
            ]
        else:
            data["honest_end"] = (
                honest_end(
                    ctx.deps.guidance,
                    ctx.w("end.serving"),
                    ["miserver"],
                    ctx.deps.runtime.installed,
                )
                + ". "
                + ctx.w("end.saved_here")
            )
    elif not next_steps:
        nxt = next_tool(out.state)
        if nxt is not None and out.subject:
            key = {"miassist_steering_serve": "cluster", "miassist_steering_save": "name"}.get(
                nxt, "feature"
            )
            next_steps = [actions.step(nxt, {key: out.subject}, ctx.w("next.continue"))]
    if key_hash and out.subject:
        chosen = {
            k: data[k]
            for k in ("feature_id", "task_id", "profile_id", "miserver_cluster_id")
            if data.get(k)
        }
        await ctx.deps.runtime.store.save_progress(
            key_hash, PLAYBOOK, out.subject, 1, {"chosen": chosen}
        )
    return build(
        ctx.deps.guidance,
        tool=tool,
        outcome=out.state,
        level=ctx.level,
        data=data,
        next_steps=next_steps,
        approval=out.approval,
        terms=("steering",),
    )


async def run(
    deps: Deps,
    ctx_: Context[Any, Any] | None,
    tool: str,
    app: str,
    body: Callable[[Ctx], Awaitable[Outcome]],
) -> CallToolResult:
    key_hash = key_hash_of(request_key(ctx_))
    ctx = Ctx(deps, await level_for(deps, key_hash))
    reason = deps.runtime.detector.unreachable_reason(app)
    if reason is not None:
        return unavailable(ctx, tool, app, reason)
    try:
        out = await body(ctx)
    except Down as down:
        return unavailable(ctx, tool, down.app, down.reason)
    except MiAssistError as error:
        return tool_error(deps, error)
    return await finish(ctx, tool, out, key_hash)


def unavailable(ctx: Ctx, tool: str, app: str, reason: str) -> CallToolResult:
    return build(
        ctx.deps.guidance,
        tool=tool,
        outcome="unavailable",
        level=ctx.level,
        data=None,
        unavailable=app,
        reason=reason,
        next_steps=[actions.step("miassist_status", {}, ctx.deps.guidance.why("app_back"))],
    )


Text = Annotated[str, Field(min_length=1, max_length=200)]
Prompt = Annotated[str, Field(min_length=1, max_length=2000)]
Ref = Annotated[str, Field(min_length=1, max_length=255)]
Strength = Annotated[float, Field(ge=-300.0, le=300.0)]


def make_find(deps: Deps) -> ToolFn:
    async def miassist_steering_find(
        ctx: Context[Any, Any],
        concept: Text,
        model: Ref | None = None,
        limit: Annotated[int, Field(ge=1, le=10)] = 5,
    ) -> Result:
        return await run(
            deps,
            ctx,
            "miassist_steering_find",
            "miworkbench",
            lambda c: actions.converge_find(c, concept, model, limit),
        )

    return miassist_steering_find


def make_try(deps: Deps) -> ToolFn:
    async def miassist_steering_try(
        ctx: Context[Any, Any],
        feature: Ref,
        prompt: Prompt,
        direction: Literal["more", "less"] = "more",
        strengths: Annotated[list[Strength], Field(min_length=2, max_length=10)] | None = None,
        approval_id: Ref | None = None,
        task_id: Ref | None = None,
        ask_again: bool = False,
    ) -> Result:
        args = TryArgs(feature, prompt, direction, strengths, approval_id, task_id, ask_again)
        return await run(
            deps,
            ctx,
            "miassist_steering_try",
            "miworkbench",
            lambda c: actions.converge_try(c, args),
        )

    return miassist_steering_try


def make_save(deps: Deps) -> ToolFn:
    async def miassist_steering_save(
        ctx: Context[Any, Any],
        name: Annotated[str, Field(min_length=1, max_length=120)],
        features: Annotated[list[dict[str, Any]], Field(min_length=1, max_length=3)],
        prompt: Prompt | None = None,
        narrative: Annotated[str, Field(max_length=2000)] | None = None,
        approval_id: Ref | None = None,
        task_id: Ref | None = None,
        ask_again: bool = False,
    ) -> Result:
        args = SaveArgs(name, features, prompt, narrative, approval_id, task_id, ask_again)
        return await run(
            deps,
            ctx,
            "miassist_steering_save",
            "miworkbench",
            lambda c: actions.converge_save(c, args),
        )

    return miassist_steering_save


def make_serve(deps: Deps) -> ToolFn:
    async def miassist_steering_serve(
        ctx: Context[Any, Any],
        cluster: Ref | None = None,
        circuit: Ref | None = None,
        hub_repo: Ref | None = None,
        prompt: Prompt | None = None,
        ask_again: bool = False,
    ) -> Result:
        chosen = [x for x in (cluster, circuit, hub_repo) if x]
        if len(chosen) != 1:
            c = Ctx(deps, await level_for(deps, key_hash_of(request_key(ctx))))
            return tool_error(deps, MiAssistError("needs_choice", c.w("error.serve_one")))
        args = ServeArgs(cluster, circuit, hub_repo, prompt, ask_again)
        return await run(
            deps,
            ctx,
            "miassist_steering_serve",
            "miserver",
            lambda c: actions.converge_serve(c, args),
        )

    return miassist_steering_serve


WRITE: frozenset[Effect] = frozenset({"store_read", "store_write", "app_read", "app_write"})
READ: frozenset[Effect] = frozenset({"store_read", "app_read"})
SPECS: tuple[ToolSpec, ...] = (
    ToolSpec("miassist_steering_find", frozenset({"miworkbench"}), True, False, READ, make_find),
    ToolSpec("miassist_steering_try", frozenset({"miworkbench"}), False, False, WRITE, make_try),
    ToolSpec("miassist_steering_save", frozenset({"miworkbench"}), False, False, WRITE, make_save),
    ToolSpec("miassist_steering_serve", frozenset({"miserver"}), False, False, WRITE, make_serve),
)
