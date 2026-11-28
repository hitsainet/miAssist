"""The five goal tools (003 FPRD §3.3, FTDD §5; A13, A26).

All five are write tools (``readOnlyHint`` false: each can file an approval or write a row) and
none is destructive. Arguments are checked by Core's strict argument layer (an unknown argument is
refused with the accepted names); results are Core's ``assist_result``.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Annotated, Any, Literal

from mcp.server.mcpserver import Context
from mcp.types import CallToolResult
from pydantic import Field

from miassist.errors import MiAssistError
from miassist.playbooks.detector_probe import actions, render
from miassist.playbooks.detector_probe.context import Ctx
from miassist.server.specs import Deps, Effect, ToolSpec
from miassist.tools.core import Result, key_hash_of, level_for, request_key

W, D, S = "miworkbench", "midataworks", "miserver"
#: Each data route and the app it needs (FPRD FR-003.9).
ROUTE_APPS = {"my_labelled_data": W, "build_with_midataworks": D}
Key = Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9-]{0,62}[a-z0-9]$")]
Text = Annotated[str, Field(min_length=1, max_length=1000)]
Rate = Annotated[float, Field(gt=0, lt=1)]
ApprovalId = Annotated[str, Field(min_length=1, max_length=128)]


async def _ctx(deps: Deps, mcp_ctx: Any) -> Ctx:
    key_hash = key_hash_of(request_key(mcp_ctx))
    return Ctx(deps, mcp_ctx, key_hash, await level_for(deps, key_hash))


async def _guarded(ctx: Ctx, run: Awaitable[CallToolResult]) -> CallToolResult:
    try:
        return await run
    except MiAssistError as err:
        return render.error(ctx, err)


def make_start(deps: Deps) -> Callable[..., Awaitable[CallToolResult]]:
    async def miassist_detector_start(
        ctx: Context[Any, Any],
        description: Text,
        key: Key | None = None,
        positive_meaning: Text | None = None,
        negative_meaning: Text | None = None,
        target_false_alarm_rate: Rate | None = None,
        adopt_existing: bool = False,
        confirm: bool = False,
    ) -> Result:
        c = await _ctx(deps, ctx)
        args = {
            "description": description,
            "key": key,
            "positive_meaning": positive_meaning,
            "negative_meaning": negative_meaning,
            "target_false_alarm_rate": target_false_alarm_rate,
            "adopt_existing": adopt_existing,
            "confirm": confirm,
        }
        return await _guarded(c, actions.converge_start(c, args))

    return miassist_detector_start


def make_data(deps: Deps) -> Callable[..., Awaitable[CallToolResult]]:
    async def miassist_detector_data(
        ctx: Context[Any, Any],
        key: Key,
        route: str | None = None,
        hf_repo: Annotated[str, Field(max_length=200)] | None = None,
        config: Annotated[str, Field(max_length=200)] | None = None,
        split_train: Annotated[str, Field(max_length=100)] | None = None,
        split_test: Annotated[str, Field(max_length=100)] | None = None,
        split_calibration: Annotated[str, Field(max_length=100)] | None = None,
        text_column: Annotated[str, Field(max_length=255)] | None = None,
        label_column: Annotated[str, Field(max_length=255)] | None = None,
        positive_values: Annotated[list[str], Field(max_length=50)] | None = None,
        ood_hf_repo: Annotated[str, Field(max_length=200)] | None = None,
        ood_split: Annotated[str, Field(max_length=100)] | None = None,
        ood_text_column: Annotated[str, Field(max_length=255)] | None = None,
        ood_label_column: Annotated[str, Field(max_length=255)] | None = None,
        ood_positive_values: Annotated[list[str], Field(max_length=50)] | None = None,
        everyday_view: Annotated[str, Field(max_length=255)] | None = None,
        nonsense_view: Annotated[str, Field(max_length=255)] | None = None,
        visibility: Literal["private", "public"] = "private",
        ask_again: bool = False,
        confirm: bool = False,
    ) -> Result:
        c = await _ctx(deps, ctx)
        args = {k: v for k, v in locals().items() if k not in ("ctx", "c", "deps")}
        return await _guarded(c, actions.converge_data(c, args))

    # The route enum holds only the routes this installation has (an absent app is never named).
    routes = tuple(r for r, app in ROUTE_APPS.items() if app in deps.runtime.installed)
    miassist_detector_data.__annotations__["route"] = Literal[routes] | None if routes else None
    return miassist_detector_data


def make_train(deps: Deps) -> Callable[..., Awaitable[CallToolResult]]:
    async def miassist_detector_train(
        ctx: Context[Any, Any],
        key: Key,
        model: Annotated[str, Field(max_length=255)] | None = None,
        approval_id: ApprovalId | None = None,
        expert_config: dict[str, Any] | None = None,
        ask_again: bool = False,
        confirm: bool = False,
    ) -> Result:
        c = await _ctx(deps, ctx)
        args = {k: v for k, v in locals().items() if k not in ("ctx", "c", "deps")}
        return await _guarded(c, actions.converge_train(c, args))

    return miassist_detector_train


def make_verdict(deps: Deps) -> Callable[..., Awaitable[CallToolResult]]:
    async def miassist_detector_verdict(
        ctx: Context[Any, Any],
        key: Key,
        probe: Annotated[str, Field(max_length=128)] | None = None,
        approval_id: ApprovalId | None = None,
        ask_again: bool = False,
        confirm: bool = False,
    ) -> Result:
        c = await _ctx(deps, ctx)
        args = {k: v for k, v in locals().items() if k not in ("ctx", "c", "deps")}
        return await _guarded(c, actions.converge_verdict(c, args))

    return miassist_detector_verdict


def make_deploy(deps: Deps) -> Callable[..., Awaitable[CallToolResult]]:
    async def miassist_detector_deploy(
        ctx: Context[Any, Any],
        key: Key | None = None,
        probe: Annotated[str, Field(max_length=128)] | None = None,
        hub_repo: Annotated[str, Field(max_length=200)] | None = None,
        below_rung2_reason: Annotated[str, Field(min_length=10, max_length=500)] | None = None,
        approval_id: ApprovalId | None = None,
        ask_again: bool = False,
        confirm: bool = False,
    ) -> Result:
        c = await _ctx(deps, ctx)
        args = {k: v for k, v in locals().items() if k not in ("ctx", "c", "deps")}
        return await _guarded(c, actions.converge_deploy(c, args))

    return miassist_detector_deploy


WRITE: frozenset[Effect] = frozenset({"store_read", "store_write", "app_read", "app_write"})

DETECTOR_SPECS: tuple[ToolSpec, ...] = (
    ToolSpec("miassist_detector_start", frozenset({W, D}), False, False, WRITE, make_start),
    ToolSpec("miassist_detector_data", frozenset({W, D}), False, False, WRITE, make_data),
    ToolSpec("miassist_detector_train", frozenset({W}), False, False, WRITE, make_train),
    ToolSpec("miassist_detector_verdict", frozenset({W}), False, False, WRITE, make_verdict),
    ToolSpec("miassist_detector_deploy", frozenset({S}), False, False, WRITE, make_deploy),
)
