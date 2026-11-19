"""One converge coroutine per tool (003 FTDD §2, §6; FTID §1): re-read the snapshot, derive the
state, act at most once, re-derive, render. Every app write goes through Core's ``AppClient.call``
(or ``WorkbenchAdapter.file_first``) with a registered route constant."""

from __future__ import annotations

import asyncio
import re
from collections.abc import Mapping
from typing import Any

from mcp.types import CallToolResult

from miassist.adapters.base import (
    AppAnswer,
    AppError,
    Handoff,
    Pending,
    Resource,
    Route,
    Unavailable,
)
from miassist.adapters.midataworks import check_version_sources
from miassist.adapters.miworkbench import canonical_payload
from miassist.errors import MiAssistError
from miassist.hub.public_check import run_public_check
from miassist.playbooks._shared import calm, pending
from miassist.playbooks.ask import Choice, ask, form_capable
from miassist.playbooks.detector_probe import defaults, flow, render, snapshot, verdict
from miassist.playbooks.detector_probe import routes as rt
from miassist.playbooks.detector_probe.context import PLAYBOOK, Ctx
from miassist.playbooks.detector_probe.flow import Derived, StepState
from miassist.results.build import build
from miassist.vendored import requests as vendored

KEY = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}[a-z0-9]$")
MAX_SUFFIX = 9
#: FTDD T2: at most this long inside one call for a download (seconds).
DOWNLOAD_WAIT_S = 10


def slug(description: str) -> str:
    words = re.findall(r"[a-z0-9]+", description.lower())[:4]
    key = "-".join(words)[:64].strip("-") or "behaviour"
    return key if len(key) >= 2 else f"{key}-x"


def app_error(err: AppError, key: str) -> MiAssistError:
    from miassist.playbooks._shared import app_hints

    steps, _ = app_hints.next_steps_of(_json(err.original), {"key": key})
    return MiAssistError(err.code, err.message or err.code, next=steps)


def _json(text: str) -> Any:
    import json

    try:
        return json.loads(text)
    except ValueError:
        return None


def honest_end_for(ctx: Ctx, derived: Derived) -> str | None:
    """The calm end of what this installation can do (FPRD §5.3), through Core's form."""
    if derived.state is StepState.DATA_CHECKED and not ctx.has("miworkbench"):
        return calm.honest_end(ctx.guidance, PLAYBOOK, "data", ["miworkbench"], ctx.installed)
    if derived.state is StepState.JUDGED and not ctx.has("miserver"):
        return calm.honest_end(ctx.guidance, PLAYBOOK, "verdict", ["miserver"], ctx.installed)
    return None


def view_summary(snap: snapshot.Snapshot) -> dict[str, dict[str, Any]]:
    """Each registered role's view id and counts (FR-003.9); nothing else of the view. The counts
    are miWorkbench's stored five (``probe_monitor_inputs.BuildCounts``): the rows a view scores
    are its positives and negatives; ``unmapped_rows`` are rows whose label value the mapping did
    not name, which miWorkbench leaves out without refusing (R1 review fix OR1-pb-20, 2026-11-16).
    """
    out = {}
    for role, view in snap.views.items():
        found = view.get("counts")
        counts: Mapping[str, Any] = found if isinstance(found, Mapping) else {}
        found_kinds = counts.get("kinds")
        kinds: Mapping[str, Any] = found_kinds if isinstance(found_kinds, Mapping) else {}
        known = "positive" in counts or "negative" in counts
        out[role] = {
            "id": view.get("id"),
            "rows": (
                int(counts.get("positive") or 0) + int(counts.get("negative") or 0)
                if known
                else None
            ),
            "positives": counts.get("positive"),
            "unmapped_rows": int(kinds.get("unmapped_label") or 0) if known else None,
        }
    return out


async def report(ctx: Ctx, tool: str, key: str) -> CallToolResult:
    """The state of the journey as this tool's step sees it; no app write."""
    snap = await snapshot.read(ctx, key)
    for app, reason in snap.unavailable.items():
        return render.unavailable(ctx, tool, app, reason, key)
    derived = flow.derive(snap, ctx.installed, ctx.chosen)
    data: dict[str, Any] = {}
    if tool == "miassist_detector_deploy":
        return await _deploy_report(ctx, tool, key)
    if tool == "miassist_detector_data":
        data["data_ready"] = flow.views_ready(snap) or derived.state is StepState.DATA_CHECKED
        data["views"] = view_summary(snap)
        dropped = sum(v.get("unmapped_rows") or 0 for v in data["views"].values())
        if dropped:
            data["caution"] = ctx.say("caution.unmapped", rows=dropped)
    if derived.state is StepState.WATCHING:
        data["events_24h"] = snap.sv_event_counts or {}
        data["not_scoring_reason"] = snap.sv_paused_reason
    end = honest_end_for(ctx, derived)
    if end is not None:
        data["honest_end"] = end
        data["summary"] = end
    return render.result(ctx, tool, derived, key, data=data)


# -- miassist_detector_start (FR-003.8) -------------------------------------------------------


async def _exists(ctx: Ctx, key: str) -> bool | Unavailable:
    answer = await ctx.client("miworkbench").call(rt.BEHAVIOUR, path_params={"key": key})
    if isinstance(answer, Unavailable):
        return answer
    return isinstance(answer, Resource)


async def converge_start(ctx: Ctx, args: Mapping[str, Any]) -> CallToolResult:
    tool = "miassist_detector_start"
    given = args.get("key")
    key = given or slug(args["description"])
    if not KEY.match(key):
        raise MiAssistError("invalid_arguments", "the key must be a lower-case slug")
    await ctx.load(key)
    reasons = {"key": ctx.say("reason.key"), "meanings": ctx.say("reason.meaning")}
    if ctx.has("miworkbench"):
        exists = await _exists(ctx, key)
        if isinstance(exists, Unavailable):
            return render.unavailable(ctx, tool, "miworkbench", exists.reason, key)
        ours = ctx.chosen.get("catalogued") == key
        if exists and ours:
            return _described(ctx, tool, key, "miworkbench")
        if exists and given:
            if not (args.get("adopt_existing") and args.get("confirm")):
                return _ask_adopt(ctx, tool, key, args)
            await ctx.remember(key, catalogued=key, catalogued_in="miworkbench", adopted=True)
            return _described(ctx, tool, key, "miworkbench")
        if exists:
            free = await _free_key(ctx, key)
            if isinstance(free, Unavailable):
                return render.unavailable(ctx, tool, "miworkbench", free.reason, key)
            key = free
            reasons["key"] = ctx.say("reason.key_taken")
            await ctx.load(key)
    proposal = {
        "key": key,
        "positive_meaning": args.get("positive_meaning") or args["description"],
        "negative_meaning": args.get("negative_meaning"),
        "target_false_alarm_rate": args.get("target_false_alarm_rate") or 0.01,
    }
    if not args.get("confirm") or (given is None):
        confirmed = await _confirm(ctx, tool, args, proposal, reasons)
        if isinstance(confirmed, CallToolResult) or confirmed is not True:
            return confirmed  # type: ignore[return-value]
    if not ctx.has("miworkbench"):
        await ctx.remember(key, catalogued=key, catalogued_in="miassist")
        return _described(ctx, tool, key, "miassist")
    body = {
        "key": key,
        "name": args["description"][:120],
        "description": args["description"],
        "positive_meaning": proposal["positive_meaning"],
        "target_fpr": proposal["target_false_alarm_rate"],
    }
    if proposal["negative_meaning"]:
        body["negative_meaning"] = proposal["negative_meaning"]
    answer = await ctx.client("miworkbench").call(rt.BEHAVIOURS_CREATE, json=body, floor_scope=key)
    if isinstance(answer, Unavailable):
        return render.unavailable(ctx, tool, "miworkbench", answer.reason, key)
    if isinstance(answer, AppError):
        return render.error(ctx, app_error(answer, key))
    await ctx.remember(key, catalogued=key, catalogued_in="miworkbench")
    return _described(ctx, tool, key, "miworkbench")


def _described(ctx: Ctx, tool: str, key: str, where: str) -> CallToolResult:
    derived = Derived(StepState.DESCRIBED, "data")
    data = {"key": key, "catalogued_in": where, "definition_version": 1}
    return render.result(ctx, tool, derived, key, data=data)


async def _free_key(ctx: Ctx, key: str) -> str | Unavailable:
    base = re.sub(r"-[0-9]$", "", key)[:61]
    for n in range(2, MAX_SUFFIX + 1):
        candidate = f"{base}-{n}"
        exists = await _exists(ctx, candidate)
        if isinstance(exists, Unavailable):
            return exists
        if not exists:
            return candidate
    raise MiAssistError("key_taken", "every nearby key is taken; choose a key of your own")


async def _confirm(
    ctx: Ctx,
    tool: str,
    args: Mapping[str, Any],
    proposal: Mapping[str, Any],
    reasons: Mapping[str, str],
) -> CallToolResult | bool | Any:
    """One confirmation: a form when the client can show one, else the teaching result whose
    ``next`` carries every proposed value (FR-003.16)."""
    accepted = {**{k: v for k, v in args.items() if v is not None}, **proposal, "confirm": True}
    accepted = {k: v for k, v in accepted.items() if v is not None}
    if form_capable(ctx.mcp):
        choice = Choice(
            name="record_it",
            title=ctx.say("choice.confirm"),
            options=("yes", "no"),
            recommended="yes",
            reason=reasons["key"],
            option_titles=(ctx.say("choice.confirm_yes"), ctx.say("choice.confirm_no")),
        )
        answered = await ask(
            ctx.mcp, ctx.guidance, tool=tool, args=accepted, choices=[choice], level=ctx.level
        )
        if hasattr(answered, "values"):
            if answered.values.get("record_it") == "yes":
                return True
            return build(
                ctx.guidance,
                tool="ask",
                outcome="declined",
                level=ctx.level,
                data={"choices": ["record_it"], "changed": False},
            )
        return answered
    derived = Derived(StepState.UNDESCRIBED, "describe")
    data = {"proposal": dict(proposal), "reasons": dict(reasons), "recorded": False}
    nxt = [{"tool": tool, "args": accepted, "why": ctx.say("state.proposed.next")}]
    return render.result(
        ctx, tool, derived, str(proposal["key"]), data=data, next_steps=nxt, state_text="proposed"
    )


def _ask_adopt(ctx: Ctx, tool: str, key: str, args: Mapping[str, Any]) -> CallToolResult:
    """A key the person typed is already recorded: ask; never read out that behaviour (A22)."""
    derived = Derived(StepState.UNDESCRIBED, "describe")
    adopt = {
        **{k: v for k, v in args.items() if v is not None},
        "adopt_existing": True,
        "confirm": True,
    }
    data = {"key_taken": key, "reasons": {"key": ctx.say("reason.adopt")}, "recorded": False}
    nxt = [{"tool": tool, "args": adopt, "why": ctx.say("reason.adopt")}]
    return render.result(ctx, tool, derived, key, data=data, next_steps=nxt, state_text="proposed")


# -- shared: miWorkbench's file-first gate (FR-003.19; Core's WorkbenchAdapter.file_first) ----


async def gate(
    ctx: Ctx,
    tool: str,
    key: str,
    kind: str,
    route: Route,
    *,
    path_params: Mapping[str, Any],
    query: Mapping[str, Any],
    body: Any,
    body_param: str | None = None,
    approval_id: str | None,
    ask_again: bool,
    again: Mapping[str, Any],
    facts: Mapping[str, Any],
    forecast: Mapping[str, Any] | None = None,
    person_reason: str | None = None,
) -> AppAnswer:
    """File first, then one call with the approved id (Core does both); this adds the repeat-call
    lookup (``_shared.pending``) and remembers the filed id. Never calls ``route`` itself."""
    client = ctx.client("miworkbench")
    canonical = canonical_payload(
        route.method, route.path, path_params, query, body, body_param=body_param
    )
    # R1 review fix (OR1-pb-7), 2026-11-16: a request miWorkbench's own schema refuses is refused
    # here, before anything is filed: the operator never approves (and spends) a request that fails.
    refused = vendored.refusals(route, query, body)
    if refused:
        raise MiAssistError(
            "invalid_arguments",
            "miWorkbench would refuse this request: " + "; ".join(refused)[:400],
            fix="change the value it names; nothing was filed",
        )
    if approval_id is None and not ask_again:
        remembered = (ctx.chosen.get("approvals") or {}).get(kind)
        approval_id = await pending.open_id(  # the merged lookup (OR1-pb-10; OVN-miassist-int-13)
            client,
            str(route.approval_action),
            payload_digest=pending.digest(canonical),
            remembered=remembered,
            include_closed=True,
        )
    summary = ctx.say("approval.summary", **facts)
    answer = await vendored.workbench(client).file_first(
        route,
        path_params=path_params,
        query=query,
        body=body,
        body_param=body_param,
        approval_id=approval_id,
        person_reason=person_reason,
        tool=tool,
        args=dict(again),
        summary=summary,
        forecast=forecast,
    )
    if isinstance(answer, Pending):
        await ctx.remember(key, approvals={kind: answer.approval["id"]})
    return answer


def four_facts(ctx: Ctx, kind: str, approval_id: str, **slots: Any) -> dict[str, str]:
    """FR-003.21: what, cost, where, how to resume (filled again once the id is known)."""
    return {
        "what": ctx.say(f"approval.{kind}.what"),
        "cost": ctx.say(f"approval.{kind}.cost", **slots),
        "where": ctx.say(f"approval.{kind}.where", id=approval_id),
        "resume": ctx.say(f"approval.{kind}.resume"),
    }


OUTCOME_STATE = {
    "pending": None,
    "rejected": StepState.REJECTED,
    "expired": StepState.EXPIRED,
    "failed": StepState.FAILED,
}


def gated_result(
    ctx: Ctx,
    tool: str,
    key: str,
    kind: str,
    answer: Pending,
    waiting: StepState,
    slots: Mapping[str, Any],
    data: Mapping[str, Any] | None = None,
) -> CallToolResult:
    approval = dict(answer.approval)
    facts = four_facts(ctx, kind, approval["id"], **slots)
    approval["summary"] = ctx.say("approval.summary", **facts)[:500]
    state = OUTCOME_STATE.get(approval["status"]) or waiting
    step = flow.KIND_STEP[kind]
    body = {"approval_facts": facts, **dict(data or {})}
    if approval.get("reason"):
        body["reason"] = calm.quote(approval["reason"], 300)
    nxt = None
    if state is waiting:
        nxt = [
            {
                "tool": tool,
                "args": dict(approval.get("call_again_with", {}).get("args") or {"key": key}),
                "why": ctx.say(f"state.{waiting.value}.next"),
            }
        ]
    return render.result(
        ctx, tool, Derived(state, step, kind), key, data=body, approval=approval, next_steps=nxt
    )


async def _workbench_down(
    ctx: Ctx, tool: str, key: str, snap: snapshot.Snapshot
) -> CallToolResult | None:
    reason = snap.unavailable.get("miworkbench") or ctx.deps.runtime.detector.unreachable_reason(
        "miworkbench"
    )
    if reason:
        return render.unavailable(ctx, tool, "miworkbench", reason, key)
    return None


def _answer_error(ctx: Ctx, tool: str, key: str, answer: AppAnswer) -> CallToolResult | None:
    if isinstance(answer, Unavailable):
        return render.unavailable(ctx, tool, answer.app, answer.reason, key)
    if isinstance(answer, AppError):
        return render.error(ctx, app_error(answer, key))
    return None


# -- miassist_detector_data, own data (FR-003.9, 9a, 9b, 3.x) ---------------------------------

OWN_NEEDS = (
    "hf_repo",
    "split_train",
    "split_test",
    "text_column",
    "label_column",
    "positive_values",
)


async def converge_data(ctx: Ctx, args: Mapping[str, Any]) -> CallToolResult:
    tool, key = "miassist_detector_data", args["key"]
    await ctx.load(key)
    route = args.get("route") or ctx.chosen.get("route")
    if route is None:
        route = "my_labelled_data" if ctx.has("miworkbench") else "build_with_midataworks"
    if route == "build_with_midataworks":
        return await converge_dataworks(ctx, args)
    snap = await snapshot.read(ctx, key)
    down = await _workbench_down(ctx, tool, key, snap)
    if down is not None:
        return down
    if snap.behaviour is None:
        return await report(ctx, tool, key)
    if flow.views_ready(snap):
        return await report(ctx, tool, key)
    missing = [n for n in OWN_NEEDS if not args.get(n)]
    if missing and "train" not in snap.views:
        derived = Derived(StepState.DESCRIBED, "data")
        nxt = [
            {
                "tool": tool,
                "args": {"key": key, "route": "my_labelled_data", **{n: f"<{n}>" for n in missing}},
                "why": ctx.say("state.described.next"),
            }
        ]
        return render.result(
            ctx, tool, derived, key, data={"needs": missing, "data_ready": False}, next_steps=nxt
        )
    await ctx.remember(key, route="my_labelled_data")
    if "train" not in snap.views:
        got = await _dataset(ctx, tool, key, args["hf_repo"], args.get("config"), "dataset_id")
        if isinstance(got, CallToolResult):
            return got
        refused = await _register_own(ctx, tool, key, snap, args, got)
        if refused is not None:
            return refused
    if args.get("ood_hf_repo") and "ood" not in snap.views:
        got = await _dataset(ctx, tool, key, args["ood_hf_repo"], None, "ood_dataset_id")
        if isinstance(got, CallToolResult):
            return got
        refused = await _register_ood(ctx, tool, key, snap, args, got)
        if refused is not None:
            return refused
    for role, step in (("everyday_text", _everyday), ("nonsense_text", _nonsense)):
        if role not in snap.views:
            stopped = await step(ctx, tool, key, snap, args)
            if stopped is not None:
                return stopped
    return await report(ctx, tool, key)


async def _dataset(
    ctx: Ctx, tool: str, key: str, repo: str, config: str | None, remember_as: str
) -> str | CallToolResult:
    """The miWorkbench dataset for exactly ``repo``: already there, or downloaded after Core's
    public check and size rule (M16, A23, A24); anything else is the operator's (operator_action).
    """
    client = ctx.client("miworkbench")
    from miassist.adapters.routes import ROUTES

    listed = await client.call(
        ROUTES.get("miworkbench.list_datasets"), params={"page": 1, "limit": 100}
    )
    if (err := _answer_error(ctx, tool, key, listed)) is not None:
        return err
    # R1 review fix (OR1-pb-8), 2026-11-16: miWorkbench lists under ``data``
    # (``DatasetListResponse``, ``schemas/dataset.py:178-182``).
    items = (
        listed.body.get("data") or []
        if isinstance(listed, Resource) and isinstance(listed.body, Mapping)
        else []
    )
    found = next((d for d in items if isinstance(d, Mapping) and d.get("hf_repo_id") == repo), None)
    if found is None:
        check = await run_public_check(ctx.deps.runtime.clients, repo, with_size=True)
        if isinstance(check, Resource | AppError | Unavailable):
            if isinstance(check, Unavailable):
                return render.unavailable(ctx, tool, check.app, check.reason, key)
            return await _handoff(ctx, tool, key)
        if isinstance(check, Handoff) or not check.public:
            return await _handoff(ctx, tool, key)
        body = {"repo_id": repo, **({"config": config} if config else {})}
        answer = await client.call(
            rt.DATASET_DOWNLOAD, json=body, public_check=check, floor_scope=key
        )
        if isinstance(answer, Handoff):
            return await _handoff(ctx, tool, key)
        if (err := _answer_error(ctx, tool, key, answer)) is not None:
            return err
        found = (
            dict(answer.body)
            if isinstance(answer, Resource) and isinstance(answer.body, Mapping)
            else {}
        )
        await ctx.remember(key, **{remember_as: found.get("id")}, licence=check.licence)
    dataset_id = str(found.get("id"))
    status = str(found.get("status") or "ready")
    for _ in range(DOWNLOAD_WAIT_S):
        if status not in ("downloading", "processing"):
            break
        await asyncio.sleep(1)
        again = await client.call(rt.DATASET, path_params={"dataset_id": dataset_id})
        if isinstance(again, Resource) and isinstance(again.body, Mapping):
            status = str(again.body.get("status") or status)
    if status in ("downloading", "processing"):
        await ctx.remember(key, downloading=True)
        return render.result(
            ctx,
            tool,
            Derived(StepState.DATASET_DOWNLOADING, "data"),
            key,
            data={"data_ready": False},
        )
    if status == "error":
        return render.result(
            ctx, tool, Derived(StepState.FAILED, "data"), key, data={"data_ready": False}
        )
    await ctx.remember(key, downloading=False, awaiting_download=False)
    return dataset_id


async def _handoff(ctx: Ctx, tool: str, key: str) -> CallToolResult:
    await ctx.remember(key, awaiting_download=True)
    derived = Derived(StepState.AWAITING_DOWNLOAD, "data")
    waiting = [{"kind": "operator_action", "detail": ctx.say("handoff.download")}]
    return render.result(ctx, tool, derived, key, data={"data_ready": False, "waiting": waiting})


def _choice(args: Mapping[str, Any], dataset_id: str) -> defaults.DataChoice:
    return defaults.DataChoice(
        dataset_id=dataset_id,
        repo=str(args["hf_repo"]),
        config=args.get("config"),
        split_train=str(args["split_train"]),
        split_test=str(args["split_test"]),
        split_calibration=args.get("split_calibration"),
        text_column=str(args["text_column"]),
        label_column=str(args["label_column"]),
        positive_values=tuple(args["positive_values"]),
    )


async def _post_view(
    ctx: Ctx, tool: str, key: str, role: str, body: Mapping[str, Any], args: Mapping[str, Any]
) -> str | CallToolResult:
    answer = await ctx.client("miworkbench").call(
        rt.PROBE_VIEWS_CREATE, json=dict(body), floor_scope=key
    )
    if (err := _answer_error(ctx, tool, key, answer)) is not None:
        return err
    view_id = (
        str(answer.body.get("id"))
        if isinstance(answer, Resource) and isinstance(answer.body, Mapping)
        else ""
    )
    await ctx.remember(key, views={role: view_id})
    return view_id


async def _register_own(
    ctx: Ctx, tool: str, key: str, snap: snapshot.Snapshot, args: Mapping[str, Any], dataset_id: str
) -> CallToolResult | None:
    negatives = list(ctx.chosen.get("unmapped") or []) if args.get("confirm") else []
    meaning = await _meaning(ctx, key)
    bodies = defaults.view_bodies(_choice(args, dataset_id), key, meaning, negatives)
    for role, body in bodies.items():
        if role in snap.views:
            continue
        got = await _post_view(ctx, tool, key, role, body, args)
        if isinstance(got, CallToolResult):
            return got
        snap.views[role] = {"id": got}
    await ctx.remember(key, unmapped=[], shared_split=not args.get("split_calibration"))
    return None


async def _register_ood(
    ctx: Ctx, tool: str, key: str, snap: snapshot.Snapshot, args: Mapping[str, Any], dataset_id: str
) -> CallToolResult | None:
    choice = defaults.DataChoice(
        dataset_id=dataset_id,
        repo=str(args["ood_hf_repo"]),
        config=None,
        split_train=str(args.get("ood_split") or args["split_test"]),
        split_test=str(args.get("ood_split") or args["split_test"]),
        split_calibration=None,
        text_column=str(args.get("ood_text_column") or args["text_column"]),
        label_column=str(args.get("ood_label_column") or args["label_column"]),
        positive_values=tuple(args.get("ood_positive_values") or args["positive_values"]),
    )
    negatives = list(ctx.chosen.get("unmapped") or []) if args.get("confirm") else []
    got = await _post_view(
        ctx,
        tool,
        key,
        "ood",
        defaults.ood_body(choice, key, await _meaning(ctx, key), negatives),
        args,
    )
    if isinstance(got, CallToolResult):
        return got
    snap.views["ood"] = {"id": got}
    return None


async def _meaning(ctx: Ctx, key: str) -> str:
    answer = await ctx.client("miworkbench").call(rt.BEHAVIOUR, path_params={"key": key})
    if isinstance(answer, Resource) and isinstance(answer.body, Mapping):
        definition = answer.body.get("definition")
        if isinstance(definition, Mapping) and definition.get("positive_meaning"):
            return str(definition["positive_meaning"])[:1000]
    return key


async def _named_view(ctx: Ctx, name: str, role: str) -> str | None:
    """A view the person NAMED, by exact id or name, with the right role; nothing else (A22)."""
    answer = await ctx.client("miworkbench").call(rt.PROBE_VIEWS, params={"role": role})
    rows = answer.body if isinstance(answer, Resource) and isinstance(answer.body, list) else []
    for row in rows:
        if (
            isinstance(row, Mapping)
            and name in (row.get("id"), row.get("name"))
            and row.get("role") == role
        ):
            return str(row.get("id"))
    return None


async def _everyday(
    ctx: Ctx, tool: str, key: str, snap: snapshot.Snapshot, args: Mapping[str, Any]
) -> CallToolResult | None:
    named = args.get("everyday_view")
    if named:
        found = await _named_view(ctx, str(named), "everyday_text")
        if found is None:
            raise MiAssistError("unknown_view", "no everyday-text view has that exact id or name")
        await ctx.remember(key, views={"everyday_text": found})
        snap.views["everyday_text"] = {"id": found}
        return None
    configured = ctx.deps.runtime.settings.everyday_text_repo
    if not configured:
        derived = Derived(StepState.VIEWS_PARTIAL, "data")
        waiting = [{"kind": "operator_action", "detail": ctx.say("handoff.everyday")}]
        return render.result(
            ctx,
            tool,
            derived,
            key,
            data={"needs": ["everyday_view"], "waiting": waiting, "data_ready": False},
        )
    repo, _, rest = configured.partition(":")
    config, _, split = rest.partition(":")
    got = await _dataset(ctx, tool, key, repo, config or None, "everyday_dataset_id")
    if isinstance(got, CallToolResult):
        return got
    view = await _post_view(
        ctx,
        tool,
        key,
        "everyday_text",
        defaults.everyday_body(got, key, config or None, split or None),
        args,
    )
    if isinstance(view, CallToolResult):
        return view
    snap.views["everyday_text"] = {"id": view}
    return None


async def _nonsense(
    ctx: Ctx, tool: str, key: str, snap: snapshot.Snapshot, args: Mapping[str, Any]
) -> CallToolResult | None:
    named = args.get("nonsense_view")
    if named:
        found = await _named_view(ctx, str(named), "nonsense_text")
        if found is None:
            raise MiAssistError("unknown_view", "no nonsense-text view has that exact id or name")
        await ctx.remember(key, views={"nonsense_text": found})
        snap.views["nonsense_text"] = {"id": found}
        return None
    answer = await ctx.client("miworkbench").call(
        rt.NONSENSE_TEXT, json=defaults.nonsense_body(key), floor_scope=key
    )
    if (err := _answer_error(ctx, tool, key, answer)) is not None:
        return err
    view = (
        answer.body.get("view")
        if isinstance(answer, Resource) and isinstance(answer.body, Mapping)
        else None
    )
    view_id = str(view.get("id")) if isinstance(view, Mapping) else ""
    await ctx.remember(key, views={"nonsense_text": view_id})
    snap.views["nonsense_text"] = {"id": view_id}
    return None


# -- miassist_detector_train (FR-003.10, FR-003.14, FR-003.15, FR-003.21; 4.x) ----------------


def accepted_config_keys() -> frozenset[str]:
    """The run config's declared names, from the vendored request schema (mirrors
    ``ProbeRunConfig``, ``extra="forbid"``)."""
    schema = vendored.lookup(rt.PROBE_RUNS)
    config = ((schema.body if schema else None) or {}).get("properties", {}).get("config", {})
    for branch in [config, *config.get("anyOf", [])]:
        if isinstance(branch, Mapping) and "properties" in branch:
            return frozenset(branch["properties"])
    return frozenset()


async def _models(ctx: Ctx) -> list[str]:
    from miassist.adapters.routes import ROUTES

    answer = await ctx.client("miworkbench").call(
        ROUTES.get("miworkbench.list_models"), params={"page": 1, "limit": 50}
    )
    body = answer.body if isinstance(answer, Resource) else None
    # R1 review fix (OR1-pb-8): ``ModelListResponse.data`` (``schemas/model.py:142-146``).
    items = body.get("data") or [] if isinstance(body, Mapping) else []
    ready = [
        str(m.get("id"))
        for m in items
        if isinstance(m, Mapping)
        and m.get("id")
        and m.get("status", "ready") in ("ready", "completed")
    ]
    if ctx.has("miserver") and ready:
        served = await ctx.client("miserver").call(ROUTES.get("miserver.list_models"))
        sbody = served.body if isinstance(served, Resource) else None
        sitems = sbody.get("data", sbody) if isinstance(sbody, Mapping) else sbody
        names = {
            str(m.get(k))
            for m in sitems or []
            if isinstance(m, Mapping)
            for k in ("id", "name", "hf_id")
        }
        both = [m for m in ready if m in names]
        return both or ready
    return ready


async def converge_train(ctx: Ctx, args: Mapping[str, Any]) -> CallToolResult:
    tool, key = "miassist_detector_train", args["key"]
    await ctx.load(key)
    snap = await snapshot.read(ctx, key)
    down = await _workbench_down(ctx, tool, key, snap)
    if down is not None:
        return down
    derived = flow.derive(snap, ctx.installed, ctx.chosen)
    if (
        derived.state in (StepState.REJECTED, StepState.EXPIRED, StepState.FAILED)
        and derived.kind == "training"
    ):
        if not args.get("ask_again"):
            return await _outcome(ctx, tool, key, snap, derived)
        await ctx.remember(key, approvals={"training": None})
    elif snap.run is not None or not flow.views_ready(snap):
        return await report(ctx, tool, key)
    model = args.get("model") or ctx.chosen.get("model_id")
    if not model:
        fits = await _models(ctx)
        if len(fits) != 1:
            return _ask_model(ctx, tool, key, fits)
        model = fits[0]
    recommendation = await ctx.client("miworkbench").call(
        rt.RULE_RECOMMENDATION,
        path_params={"dataset_id": snap.views["train"]["id"]},
        params={"model_id": model},
    )
    rec = (
        recommendation.body
        if isinstance(recommendation, Resource) and isinstance(recommendation.body, Mapping)
        else {}
    )
    body, reasons = defaults.run_body(
        key=key,
        model_id=str(model),
        views=snap.views,
        rules=list(rec.get("rules") or []),
        target_fpr=ctx.chosen.get("target_fpr"),
        expert_config=args.get("expert_config"),
        accepted=accepted_config_keys(),
    )
    forecast_answer = await ctx.client("miworkbench").call(rt.RUN_FORECAST, json=body)
    forecast = (
        forecast_answer.body
        if isinstance(forecast_answer, Resource) and isinstance(forecast_answer.body, Mapping)
        else {}
    )
    if forecast.get("checked") and forecast.get("fits") is False:
        raise MiAssistError(
            "run_will_not_fit",
            "the forecast says this run does not fit in memory",
        )
    seconds = ((forecast.get("time_forecast") or {}).get("seconds") or {}).get("typical")
    slots = {
        "minutes": round(seconds / 60) if seconds else "?",
        "gib": forecast.get("needed_gib", "?"),
    }
    await ctx.remember(key, model_id=model)
    again = {
        "key": key,
        "model": model,
        **({"expert_config": args["expert_config"]} if args.get("expert_config") else {}),
    }
    answer = await gate(
        ctx,
        tool,
        key,
        "training",
        rt.PROBE_RUNS,
        path_params={},
        query={},
        body=body,
        approval_id=args.get("approval_id"),
        ask_again=bool(args.get("ask_again")),
        again=again,
        facts=four_facts(ctx, "training", "-", **slots),
        forecast={"minutes": slots["minutes"], "needed_gib": slots["gib"]},
    )
    data = {
        "trained": False,
        "forecast": {"needed_gib": forecast.get("needed_gib"), "minutes": slots["minutes"]},
        "rules": body.get("config", {}).get("rules", []),
        "reasons": {k: ctx.say(v) for k, v in reasons.items()},
        "model": model,
    }
    if isinstance(answer, Pending):
        return gated_result(
            ctx, tool, key, "training", answer, StepState.TRAIN_WAITING, slots, data
        )
    if (err := _answer_error(ctx, tool, key, answer)) is not None:
        return err
    run_id = (
        answer.body.get("id")
        if isinstance(answer, Resource) and isinstance(answer.body, Mapping)
        else None
    )
    await ctx.remember(key, run_id=run_id)
    return render.result(
        ctx, tool, Derived(StepState.TRAINING, "train"), key, data={**data, "run_id": run_id}
    )


def _ask_model(ctx: Ctx, tool: str, key: str, fits: list[str]) -> CallToolResult:
    derived = Derived(StepState.VIEWS_READY, "train")
    data = {"models": fits[:10], "reasons": {"model": ctx.say("reason.model_many")}}
    nxt = [
        {"tool": tool, "args": {"key": key, "model": m}, "why": ctx.say("reason.model_many")}
        for m in fits[:3]
    ]
    return render.result(ctx, tool, derived, key, data=data, next_steps=nxt or None)


async def _outcome(
    ctx: Ctx, tool: str, key: str, snap: snapshot.Snapshot, derived: Derived
) -> CallToolResult:
    """A rejected, expired or failed request: shown with its reason; nothing filed (FR-003.22)."""
    data: dict[str, Any] = {}
    detail = dict(derived.detail or {})
    reason = detail.get("reason", detail.get("decision_reason"))
    if reason:
        data["reason"] = calm.quote(reason, 300)
    approval = None
    if derived.kind in snap.approvals and derived.kind != "send":
        from miassist.results.approvals import approval_object

        approval = approval_object(
            "miworkbench",
            snap.approvals[derived.kind],
            style="file_first",
            summary=ctx.say(f"approval.{derived.kind}.what"),
        )
    hints, said = app_hints_of(snap, key)
    return render.result(
        ctx,
        tool,
        derived,
        key,
        data={**data, "app_says": said},
        approval=approval,
        next_steps=hints or None,
    )


def app_hints_of(snap: snapshot.Snapshot, key: str) -> tuple[list[dict[str, Any]], list[str]]:
    from miassist.playbooks._shared import app_hints

    return app_hints.next_steps_of(snap.run or {}, {"key": key})


# -- miassist_detector_verdict (FR-003.11, FR-003.17; 5.x) -------------------------------------


async def converge_verdict(ctx: Ctx, args: Mapping[str, Any]) -> CallToolResult:
    tool, key = "miassist_detector_verdict", args["key"]
    await ctx.load(key)
    snap = await snapshot.read(ctx, key)
    down = await _workbench_down(ctx, tool, key, snap)
    if down is not None:
        return down
    derived = flow.derive(snap, ctx.installed, ctx.chosen)
    if (
        derived.state in (StepState.REJECTED, StepState.EXPIRED, StepState.FAILED)
        and derived.kind == "evaluation"
    ):
        if not args.get("ask_again"):
            return await _outcome(ctx, tool, key, snap, derived)
        await ctx.remember(key, approvals={"evaluation": None})
    elif flow.evaluated_everywhere(snap) or derived.state is StepState.JUDGED:
        return _judged(ctx, tool, key, snap)
    elif derived.state is StepState.EVALUATING:
        return await report(ctx, tool, key)
    probe_id = args.get("probe") or ctx.chosen.get("probe_id") or snapshot.selected_probe(snap.run)
    if not probe_id or (
        str((snap.run or {}).get("status")) != "completed" and not args.get("probe")
    ):
        return await report(ctx, tool, key)
    ids = [snap.views[r]["id"] for r in defaults.EVAL_ROLES if r in snap.views]
    # R1 review fix (OR1-pb-7), 2026-11-16: always send the sample size. Without it miWorkbench
    # refuses a corpus-sized view after the operator's approval is consumed (A40); a smaller view
    # is scored whole (``services/eval_sample_size.py``).
    query = {"sample_rows": defaults.MAX_UNSAMPLED_ROWS}
    await ctx.remember(key, probe_id=probe_id)
    slots = {"sets": len(ids)}
    answer = await gate(
        ctx,
        tool,
        key,
        "evaluation",
        rt.PROBE_EVALUATE,
        path_params={"probe_id": probe_id},
        query=query,
        body=ids,
        body_param="dataset_ids",
        approval_id=args.get("approval_id"),
        ask_again=bool(args.get("ask_again")),
        again={"key": key, "probe": probe_id},
        facts=four_facts(ctx, "evaluation", "-", **slots),
    )
    if isinstance(answer, Pending):
        return gated_result(
            ctx,
            tool,
            key,
            "evaluation",
            answer,
            StepState.VERDICT_WAITING,
            slots,
            {"probe_id": probe_id},
        )
    if (err := _answer_error(ctx, tool, key, answer)) is not None:
        return err
    task = (
        answer.body.get("task_id")
        if isinstance(answer, Resource) and isinstance(answer.body, Mapping)
        else None
    )
    await ctx.remember(key, evaluation_task=task)
    return render.result(
        ctx, tool, Derived(StepState.EVALUATING, "verdict"), key, data={"probe_id": probe_id}
    )


def _judged(ctx: Ctx, tool: str, key: str, snap: snapshot.Snapshot) -> CallToolResult:
    f = verdict.facts(snap.report or {}, shared_split=bool(ctx.chosen.get("shared_split")))
    say = ctx.say
    derived = Derived(StepState.JUDGED, "deploy")
    data: dict[str, Any] = {
        "probe_id": ((snap.report or {}).get("probe") or {}).get("id"),
        "rung": f.rung,
        "facts": f.as_data(),
    }
    end = honest_end_for(ctx, derived)
    if end is not None:
        data["honest_end"] = end
    summary = verdict.expert_line(f, say)
    return render.result(
        ctx, tool, derived, key, data=data, summary=summary, what=verdict.render(f, say)
    )


async def converge_dataworks(ctx: Ctx, args: Mapping[str, Any]) -> CallToolResult:
    """The miDataworks route (FR-003.7, FR-003.20; FTASKS 7.1 - 7.4): read the journey, explain the
    next step, run the send when it is next (once; the app runs it after the operator's yes), and
    record its ``run_request``. The authoring steps are the person's, in miDataworks."""
    tool, key = "miassist_detector_data", args["key"]
    await ctx.remember(key, route="build_with_midataworks")
    snap = await snapshot.read(ctx, key)
    reason = snap.unavailable.get("midataworks") or ctx.deps.runtime.detector.unreachable_reason(
        "midataworks"
    )
    if reason:
        return render.unavailable(ctx, tool, "midataworks", reason, key)
    derived = flow.derive(snap, ctx.installed, ctx.chosen)
    if (
        derived.state in (StepState.REJECTED, StepState.EXPIRED, StepState.FAILED)
        and derived.kind == "send"
    ):
        # Confirmation fix (C-int-1), 2026-11-16: the send follows FR-003.22 like 003's other
        # gates: its rejected, expired or failed outcome is shown; only ``ask_again`` sends again.
        if not args.get("ask_again") or not ctx.has("miworkbench"):
            return await _outcome(ctx, tool, key, snap, derived)
        await ctx.remember(key, approvals={"send": None})
        return await _send(ctx, tool, key, snap, args)
    step = (derived.detail or {}).get("step") or (snap.dw_status or {}).get("next_step")
    if step == "resolve" and not ctx.chosen.get("definition_recorded"):
        # miAssist reads the definition itself; the app's reason (e.g. that another app is not
        # configured there) is never relayed (FR-003.7).
        await ctx.client("midataworks").call(rt.DW_BEHAVIOUR_RESOLVE, path_params={"key": key})
        await ctx.remember(key, definition_recorded=True)
    if derived.state is StepState.DW_JOURNEY_STEP and step == "send" and ctx.has("miworkbench"):
        return await _send(ctx, tool, key, snap, args)
    if snap.dw_send and snap.dw_send.get("run_request"):
        await ctx.remember(key, run_request=_ids(snap.dw_send["run_request"]))
    data: dict[str, Any] = {
        "data_ready": derived.state is StepState.DATA_CHECKED or flow.views_ready(snap)
    }
    if derived.state is StepState.DW_JOURNEY_STEP and step:
        texts = ctx.guidance.playbooks["detector-probe"].texts
        title = (snap.dw_status or {}).get("next_title")
        data["journey_step"] = step
        data["explain_step"] = (
            ctx.say(f"dw.{step}") if f"dw.{step}" in texts else calm.quote(title or step, 120)
        )
        data["waiting"] = [{"kind": "operator_action", "detail": ctx.say("handoff.dw_step")}]
    end = honest_end_for(ctx, derived)
    if end is not None:
        data["honest_end"] = end
        data["summary"] = end
    return render.result(ctx, tool, derived, key, data=data)


def _ids(run_request: Any) -> dict[str, Any]:
    """Only the ids of the send's run request (``send_service.py:817-834``)."""
    if not isinstance(run_request, Mapping):
        return {}
    return {
        k: run_request.get(k)
        for k in ("train_dataset_id", "eval_dataset_ids", "calibration_dataset_id")
    }


async def _send(
    ctx: Ctx, tool: str, key: str, snap: snapshot.Snapshot, args: Mapping[str, Any]
) -> CallToolResult:
    """One POST; ``private`` unless the person said ``public`` (Q9, A14); never an approval id;
    a repeated call with the pending row present sends nothing (A18). Confirmation fix (C-int-1),
    2026-11-16: a rejected, expired or failed send of the same sets is found too and reported, so
    it is sent again only with ``ask_again`` (FR-003.22); an open one is found even then."""
    body = {
        "set_ids": list((snap.dw_status or {}).get("set_ids") or []),
        "visibility": "public" if args.get("visibility") == "public" else "private",
    }
    client = ctx.client("midataworks")
    found = await pending.open_id(  # the merged lookup: the digest over the keys sent (OR1-pb-10b)
        client,
        "hub_push",
        payload_digest=pending.digest(body),
        remembered=(ctx.chosen.get("approvals") or {}).get("send"),
        keys=tuple(body),
        include_closed=not args.get("ask_again"),
    )
    if found is not None:
        await ctx.remember(key, approvals={"send": found})
        return await report(ctx, tool, key)
    if not (args.get("confirm") or args.get("ask_again")):
        return _hold_send(ctx, tool, key, body)
    stopped = await _screen_sets(ctx, [str(s) for s in body["set_ids"]])
    if stopped is not None:
        return render.unavailable(ctx, tool, "midataworks", stopped.reason, key)
    answer = await client.call(rt.DW_DETECTOR_SETS_SEND, json=body)
    if isinstance(answer, AppError) and answer.code.endswith("send_refused"):
        return _checks_refused(ctx, tool, key, answer)
    slots = {"visibility": body["visibility"]}
    if isinstance(answer, Pending):
        await ctx.remember(key, approvals={"send": answer.approval["id"]})
        approval = dict(answer.approval)
        facts = four_facts(ctx, "send", approval["id"], **slots)
        approval["summary"] = ctx.say("approval.summary", **facts)[:500]
        return render.result(
            ctx,
            tool,
            Derived(StepState.DW_SEND_WAITING, "data", "send"),
            key,
            data={"approval_facts": facts, "visibility": body["visibility"], "data_ready": False},
            approval=approval,
            next_steps=[
                {
                    "tool": "miassist_status",
                    "args": {"playbook": PLAYBOOK, "subject": key},
                    "why": ctx.say("state.dw_send_waiting.next"),
                }
            ],
        )
    if (err := _answer_error(ctx, tool, key, answer)) is not None:
        return err
    return await report(ctx, tool, key)


def _hold_send(ctx: Ctx, tool: str, key: str, body: Mapping[str, Any]) -> CallToolResult:
    """Confirmation fix (C-int-2), 2026-11-16 (OVN-miassist-int-31): miDataworks marks its sets
    step done at ONE set, while the person may still be making the rest (its own title: "main and
    one per sub-question"), and nothing it answers says how many there will be. Making the sets is
    the person's authoring step (FPRD Q1, FTID §7), so the send waits for the person to say the
    sets are complete (``confirm: true``; ``ask_again`` after a closed send also counts). Nothing
    is filed or sent here."""
    n = len(body["set_ids"])
    data = {
        "data_ready": False,
        "journey_step": "check",
        "explain_step": ctx.say("dw.send_confirm", n=n),
        "sets_to_send": n,
        "visibility": body["visibility"],
    }
    again = {"key": key, "route": "build_with_midataworks", "confirm": True}
    if body["visibility"] == "public":
        again["visibility"] = "public"
    derived = Derived(StepState.DW_JOURNEY_STEP, "data", detail={"step": "check"})
    return render.result(
        ctx,
        tool,
        derived,
        key,
        data=data,
        next_steps=[{"tool": tool, "args": again, "why": ctx.say("dw.send_confirm.next")}],
    )


async def _screen_sets(ctx: Ctx, set_ids: list[str]) -> Unavailable | None:
    """R3 review fix (OR3-int-2), 2026-11-16 (the operator's decision, OVN-miassist-int-23): the
    send publishes each role's version to the Hub (``send_service._publish_units``), so every
    version a set names (its roles and borrowed roles) passes Core's lineage screen first; a
    version whose lineage reaches a source imported with a credential refuses
    ``source_needs_operator`` and nothing is filed. A set that cannot be read refuses."""
    client = ctx.client("midataworks")
    versions: list[str] = []
    for set_id in set_ids:
        answer = await client.call(rt.DW_DETECTOR_SET, path_params={"set_id": set_id})
        if isinstance(answer, Unavailable):
            return answer
        body = answer.body if isinstance(answer, Resource) else None
        roles = body.get("roles") if isinstance(body, Mapping) else None
        borrowed = body.get("borrowed_roles", []) if isinstance(body, Mapping) else None
        named = [*(roles or []), *(borrowed or [])] if isinstance(roles, list) else []
        ids = [r.get("version_id") for r in named if isinstance(r, Mapping)]
        if (
            not roles
            or not isinstance(borrowed, list)
            or len(ids) != len(named)
            or not all(isinstance(i, str) and i for i in ids)
        ):
            raise MiAssistError("source_unchecked", ctx.say("error.set_unchecked", set_id=set_id))
        versions += [str(i) for i in ids]
    for version_id in dict.fromkeys(versions):
        stopped = await check_version_sources(client, version_id)
        if isinstance(stopped, Unavailable):
            return stopped
    return None


def _checks_refused(ctx: Ctx, tool: str, key: str, answer: AppError) -> CallToolResult:
    """R3 review fix (OR3-int-3): miDataworks ran the sets' checks before filing and one refuses
    (409 ``send_refused``; nothing was filed). The check step stays the operator's, with why."""
    data = {
        "data_ready": False,
        "journey_step": "check",
        "explain_step": ctx.say("dw.check_refused", reason=calm.quote(answer.message, 300)),
        "waiting": [{"kind": "operator_action", "detail": ctx.say("handoff.dw_step")}],
    }
    derived = Derived(StepState.DW_JOURNEY_STEP, "data", detail={"step": "check"})
    return render.result(ctx, tool, derived, key, data=data)


# -- miassist_detector_deploy (FR-003.12, FR-003.6, FR-003.28; 6.x) ----------------------------


async def _server_probe(
    ctx: Ctx, *, probe_id: str | None = None, hub_repo: str | None = None, name: str | None = None
) -> dict[str, Any] | Unavailable | None:
    """The miServer probe that EXACTLY matches an id, a Hub repository or a name (A22)."""
    answer = await ctx.client("miserver").call(rt.SV_PROBES)
    if isinstance(answer, Unavailable):
        return answer
    body = answer.body if isinstance(answer, Resource) else None
    items = body.get("data", body) if isinstance(body, Mapping) else body
    for item in items or []:
        if not isinstance(item, Mapping):
            continue
        if (
            (probe_id and item.get("id") == probe_id)
            or (hub_repo and item.get("hf_id") == hub_repo)
            or (name and item.get("name") == name)
        ):
            return {"id": str(item.get("id"))}
    return None


async def converge_deploy(ctx: Ctx, args: Mapping[str, Any]) -> CallToolResult:
    tool = "miassist_detector_deploy"
    key = args.get("key") or args.get("probe") or slug(str(args.get("hub_repo") or "detector"))
    await ctx.load(key)
    reason = ctx.deps.runtime.detector.unreachable_reason("miserver")
    if reason:
        return render.unavailable(ctx, tool, "miserver", reason, key)
    if args.get("probe") or args.get("hub_repo"):
        found = await _server_probe(ctx, probe_id=args.get("probe"), hub_repo=args.get("hub_repo"))
        if isinstance(found, Unavailable):
            return render.unavailable(ctx, tool, "miserver", found.reason, key)
        if found is not None:
            await ctx.remember(key, miserver_probe_id=found["id"], hub_repo=None)
        elif args.get("hub_repo"):
            await ctx.remember(key, hub_repo=args["hub_repo"])
        else:
            raise MiAssistError("unknown_probe", "miServer holds no probe with that exact id")
        return await _deploy_report(ctx, tool, key)
    if ctx.chosen.get("miserver_probe_id") or not ctx.has("miworkbench"):
        return await _deploy_report(ctx, tool, key)
    snap = await snapshot.read(ctx, key)
    down = await _workbench_down(ctx, tool, key, snap)
    if down is not None:
        return down
    derived = flow.derive(snap, ctx.installed, ctx.chosen)
    if (
        derived.state in (StepState.REJECTED, StepState.EXPIRED, StepState.FAILED)
        and derived.kind == "definition"
    ):
        if not args.get("ask_again"):
            return await _outcome(ctx, tool, key, snap, derived)
        await ctx.remember(key, approvals={"definition": None})
    elif not flow.evaluated_everywhere(snap):
        return await report(ctx, tool, key)
    probe = (snap.report or {}).get("probe") or {}
    probe_id = str(probe.get("id") or ctx.chosen.get("probe_id"))
    rung = int(probe.get("rung") or 0)
    reason_text = args.get("below_rung2_reason")
    if rung < 2 and not reason_text:
        data = {"rung": rung, "needs": ["below_rung2_reason"], "armed": False}
        return render.result(
            ctx,
            tool,
            Derived(StepState.JUDGED, "deploy"),
            key,
            data=data,
            next_steps=[
                {
                    "tool": tool,
                    "args": {"key": key, "below_rung2_reason": "<your reason>"},
                    "why": ctx.say("reason.below_rung2"),
                }
            ],
        )
    built = await _built_definition(ctx, probe_id)
    if built is None:
        body: dict[str, Any] = {}
        if rung < 2:
            body["acknowledge_below_rung2"] = {"reason": reason_text}
        again = {"key": key, **({"below_rung2_reason": reason_text} if reason_text else {})}
        answer = await gate(
            ctx,
            tool,
            key,
            "definition",
            rt.PROBE_DEFINITION_BUILD,
            path_params={"probe_id": probe_id},
            query={},
            body=body,
            approval_id=args.get("approval_id"),
            ask_again=bool(args.get("ask_again")),
            again=again,
            facts=four_facts(ctx, "definition", "-"),
            person_reason=reason_text if rung < 2 else None,
        )
        if isinstance(answer, Pending):
            return gated_result(
                ctx,
                tool,
                key,
                "definition",
                answer,
                StepState.DEPLOY_WAITING,
                {},
                {"probe_id": probe_id, "armed": False},
            )
        if (err := _answer_error(ctx, tool, key, answer)) is not None:
            return err
        task = (
            answer.body.get("task_id")
            if isinstance(answer, Resource) and isinstance(answer.body, Mapping)
            else None
        )
        await ctx.remember(key, definition_task=task, probe_id=probe_id)
        built = await _built_definition(ctx, probe_id)
        if built is None:
            return render.result(
                ctx,
                tool,
                Derived(StepState.DEPLOY_BUILDING, "deploy"),
                key,
                data={"probe_id": probe_id, "armed": False},
            )
    return await _import(ctx, tool, key, built)


async def _built_definition(ctx: Ctx, probe_id: str) -> dict[str, Any] | None:
    answer = await ctx.client("miworkbench").call(
        rt.PROBE_DEFINITION, path_params={"probe_id": probe_id}
    )
    if isinstance(answer, Resource) and isinstance(answer.body, Mapping) and answer.body:
        return dict(answer.body)
    return None


async def _import(ctx: Ctx, tool: str, key: str, document: dict[str, Any]) -> CallToolResult:
    """Import with ``on_conflict=fail``; on a conflict, adopt the existing probe by identity, never
    rename (FTID §3.5). Parity and arming are the operator's (A14): neither route is registered."""
    client = ctx.client("miserver")
    answer = await client.call(
        rt.SV_PROBES_IMPORT, params={"on_conflict": "fail"}, json=document, floor_scope=key
    )
    if isinstance(answer, Unavailable):
        return render.unavailable(ctx, tool, "miserver", answer.reason, key)
    if isinstance(answer, AppError) and name_conflict(answer):
        found = await _server_probe(ctx, name=str(document.get("name") or ""))
        if not isinstance(found, dict):
            return render.error(ctx, app_error(answer, key))
        probe_id = found["id"]
    elif isinstance(answer, AppError):
        return render.error(ctx, app_error(answer, key))
    else:
        body = answer.body if isinstance(answer, Resource) else None
        inner = body.get("data", body) if isinstance(body, Mapping) else {}
        probe_id = str((inner or {}).get("id"))
    await ctx.remember(key, miserver_probe_id=probe_id)
    return await _deploy_report(ctx, tool, key)


def name_conflict(answer: AppAnswer) -> bool:
    """miServer's import conflict: 422 ``VALIDATION_ERROR`` with ``details.code`` ``NAME_CONFLICT``
    (``services/probe_service.py:286-306``, ``core/errors.py:638-642``), never a 409. R1 review fix
    (OR1-pb-9), 2026-11-16."""
    if not isinstance(answer, AppError) or answer.status != 422:
        return False
    body = _json(answer.original)
    error = body.get("error") if isinstance(body, Mapping) else None
    details = error.get("details") if isinstance(error, Mapping) else None
    return isinstance(details, Mapping) and details.get("code") == "NAME_CONFLICT"


async def _deploy_report(ctx: Ctx, tool: str, key: str) -> CallToolResult:
    snap = await snapshot.read(ctx, key)
    reason = snap.unavailable.get("miserver")
    if reason:
        return render.unavailable(ctx, tool, "miserver", reason, key)
    derived = flow.derive(snap, ctx.installed, ctx.chosen)
    data: dict[str, Any] = {
        "miserver_probe_id": ctx.chosen.get("miserver_probe_id"),
        "armed": snap.sv_armed,
    }
    if derived.state is StepState.AWAITING_ARM:
        data["waiting"] = [{"kind": "operator_action", "detail": ctx.say("handoff.arm")}]
    elif derived.state is StepState.AWAITING_HUB_IMPORT:
        data["waiting"] = [{"kind": "operator_action", "detail": ctx.say("handoff.hub_import")}]
    elif derived.state is StepState.WATCHING:
        data["events_24h"] = snap.sv_event_counts or {}
        data["not_scoring_reason"] = snap.sv_paused_reason
    return render.result(ctx, tool, derived, key, data=data)
