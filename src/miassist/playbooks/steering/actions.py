"""The four converging actions of the steering playbook (005 FTDD §1, §6; FTID §3.2-§3.4).

Every GPU run goes through Core's ``WorkbenchAdapter.file_first`` (A18, A32): the first call files
the canonical payload through ``POST /api/v1/mcp/approvals`` and returns the approval; a later call
reads its status; only an ``approved`` status lets Core make the ONE route call carrying the id. The
repeat-call lookup digests Core's whole filed payload, ``_method`` and ``_route`` included (A43,
V-5). Imports never activate (Core's ``forbidden``); the trial is one per imported cluster per hour
(Core's floor limit, ``floor_scope`` = the miServer cluster id); activation is the operator's.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Final

from miassist.adapters import steering as st
from miassist.adapters.base import AppClient, AppError, Pending, Resource, Route, Unavailable
from miassist.adapters.miworkbench import WorkbenchAdapter, canonical_payload
from miassist.errors import MiAssistError
from miassist.playbooks._shared import pending
from miassist.playbooks.steering import fluency, strengths
from miassist.playbooks.steering.flow import TASK_FAILED, TASK_RUNNING
from miassist.server.specs import Deps
from miassist.vendored import requests

POLL_WINDOW_S = 10.0
POLL_INTERVAL_S = 1.0
GENERATION: Final = {"max_new_tokens": 96, "temperature": 0.7, "top_p": 0.9}
BUDGET: Final = {"intensity": 1.0, "intensity_range": [0.0, 1.0]}
TRIAL_TOKENS: Final = 96


class Down(Exception):
    def __init__(self, app: str, reason: str) -> None:
        super().__init__(reason)
        self.app = app
        self.reason = reason


@dataclass
class Ctx:
    deps: Deps
    level: str

    @property
    def words(self) -> dict[str, str]:
        return self.deps.guidance.playbooks["steering"].texts

    def w(self, key: str, **slots: Any) -> str:
        return self.deps.guidance.render(self.words[key], slots).text

    def client(self, app: str) -> AppClient:
        return self.deps.runtime.clients[app]

    def has(self, app: str) -> bool:
        return app in self.deps.runtime.installed

    def workbench(self) -> WorkbenchAdapter:
        """Core's file-first adapter over the production schema lookup (003's
        ``miassist.vendored.requests``; a route it does not list files nothing)."""
        return requests.workbench(self.client("miworkbench"))


@dataclass
class Outcome:
    state: str
    fields: dict[str, Any] = field(default_factory=dict)
    waiting: list[dict[str, Any]] = field(default_factory=list)
    next_steps: list[dict[str, Any]] = field(default_factory=list)
    approval: dict[str, Any] | None = None
    subject: str | None = None
    slots: dict[str, Any] = field(default_factory=dict)


def step(tool: str, args: Mapping[str, Any], why: str) -> dict[str, Any]:
    return {"tool": tool, "args": dict(args), "why": why}


async def get(client: AppClient, route: Route | str, **kw: Any) -> Any | None:
    target = client.guards.registry.get(route) if isinstance(route, str) else route
    answer = await client.call(target, **kw)
    if isinstance(answer, Resource):
        body = answer.body
        if (
            client.app == "miserver"
            and isinstance(body, Mapping)
            and "data" in body
            and "success" in body
        ):
            return body["data"]  # miServer's {success, data, error} envelope
        return body
    if isinstance(answer, Unavailable):
        raise Down(client.app, answer.reason)
    if isinstance(answer, AppError):
        if answer.status == 404:
            return None
        raise MiAssistError(answer.code, answer.message or answer.code)
    return None


def items(body: Any, *keys: str) -> list[dict[str, Any]]:
    if isinstance(body, list):
        return [i for i in body if isinstance(i, dict)]
    if isinstance(body, Mapping):
        for key in (*keys, "items", "data", "results"):
            value = body.get(key)
            if isinstance(value, list):
                return [i for i in value if isinstance(i, dict)]
    return []


# -- find ------------------------------------------------------------------------------------------


async def converge_find(ctx: Ctx, concept: str, model: str | None, limit: int) -> Outcome:
    wb = ctx.client("miworkbench")
    listed = items(
        await get(wb, st.EXTRACTIONS, params={"status_filter": "completed", "limit": 50}),
        "extractions",
    )
    if model:
        listed = [e for e in listed if model.lower() in str(e.get("model_name") or "").lower()]
    listed.sort(key=lambda e: str(e.get("created_at") or ""), reverse=True)
    candidates: list[dict[str, Any]] = []
    sae_models: dict[str, Any] = {}
    for extraction in listed[:3]:
        sae_id = extraction.get("external_sae_id")
        body = await get(
            wb,
            st.EXTRACTION_FEATURES,
            path_params={"extraction_id": extraction["id"]},
            params={
                "search": concept,
                "limit": limit,
                "sort_by": "activation_freq",
                "sort_order": "desc",
            },
        )
        if sae_id and sae_id not in sae_models:
            sae = await get(wb, st.SAE, path_params={"sae_id": sae_id}) or {}
            sae_models[sae_id] = (sae.get("model_id"), sae.get("layer"))
        model_id, sae_layer = sae_models.get(str(sae_id), (None, None))
        for feature in items(body, "features"):
            label = feature.get("name") or ctx.w(
                "label.unlabelled", index=feature.get("neuron_index")
            )
            candidates.append(
                {
                    "feature_id": feature.get("id"),
                    "neuron_index": feature.get("neuron_index"),
                    "label": label,
                    "label_source": "machine-written",
                    "activation_frequency": feature.get("activation_frequency"),
                    "max_activation": feature.get("max_activation"),
                    "sae_id": sae_id,
                    "layer": extraction.get("layer_index", sae_layer),
                    "model_id": model_id,
                }
            )
    candidates = candidates[:limit]
    lines = [
        ctx.w(
            "find.line",
            n=n,
            label=c["label"],
            index=c["neuron_index"],
            freq=c["activation_frequency"],
            max=c["max_activation"],
        )
        for n, c in enumerate(candidates, start=1)
    ] or [ctx.w("find.none")]
    next_steps = [
        step("miassist_steering_try", {"feature": c["feature_id"]}, ctx.w("find.choose"))
        for c in candidates
    ]
    return Outcome(
        "feature_chosen" if candidates else "nothing_found",
        {"candidates": candidates, "summary_lines": lines},
        next_steps=next_steps,
    )


# -- the feature and its SAE ----------------------------------------------------------------------


async def feature_facts(ctx: Ctx, feature_id: str) -> dict[str, Any]:
    wb = ctx.client("miworkbench")
    feature = await get(wb, st.FEATURE, path_params={"feature_id": feature_id})
    if not isinstance(feature, Mapping):
        raise MiAssistError("feature_not_found", ctx.w("error.feature_not_found"))
    extraction: Mapping[str, Any] = {}
    for item in items(await get(wb, st.EXTRACTIONS, params={"limit": 50}), "extractions"):
        if item.get("id") == feature.get("extraction_job_id"):
            extraction = item
    sae_id = extraction.get("external_sae_id")
    sae = (await get(wb, st.SAE, path_params={"sae_id": sae_id}) if sae_id else None) or {}
    layer = extraction.get("layer_index")
    return {
        "feature_id": feature_id,
        "neuron_index": feature.get("neuron_index"),
        "label": feature.get("name"),
        "max_activation": feature.get("max_activation"),
        "sae_id": sae_id,
        "model_id": sae.get("model_id"),
        "layer": layer if layer is not None else sae.get("layer"),
    }


def gpu_route(ctx: Ctx, route_id: str) -> Route:
    registry = ctx.client("miworkbench").guards.registry
    try:
        return registry.get(route_id)
    except KeyError:
        raise MiAssistError(
            "steering_gate_not_ready",
            ctx.w("error.gate_not_ready"),
            fix=ctx.w("error.gate_not_ready_fix"),
        ) from None


#: ``SteeringTaskStatus.status`` (miWorkbench ``schemas/steering.py:414-429`` at 69bd59bba).
TASK_DONE: Final = frozenset({"success"})


def task_status(ctx: Ctx, task_id: str | None, body: Any) -> tuple[str, str | None]:
    """``(status, error)`` of a ``SteeringResultResponse``: its ``status`` is an OBJECT,
    ``{task_id, status, percent, message, error, ...}`` (R1 review fix OR1-pb-2, 2026-11-16).
    FAIL CLOSED: any other shape, or a status outside miWorkbench's enum, is an error and never a
    finished task (a running or failed sweep must not read as done)."""
    inner = body.get("status") if isinstance(body, Mapping) else None
    status = inner.get("status") if isinstance(inner, Mapping) else None
    known = TASK_RUNNING | TASK_FAILED | TASK_DONE
    if not isinstance(status, str) or status.lower() not in known:
        raise MiAssistError(
            "task_unreadable",
            ctx.w("error.task_unreadable", task_id=task_id or "-"),
            fix=ctx.w("error.task_unreadable_fix"),
        )
    error = inner.get("error") if isinstance(inner, Mapping) else None
    return status.lower(), (str(error) if error else None)


async def poll_task(ctx: Ctx, task_id: str) -> dict[str, Any]:
    """The task, read until it ends or ``POLL_WINDOW_S`` passes (the last read either way)."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + POLL_WINDOW_S
    wb = ctx.client("miworkbench")
    while True:
        body = await get(wb, st.STEERING_RESULT, path_params={"task_id": task_id}) or {}
        status, _ = task_status(ctx, task_id, body)
        if status not in TASK_RUNNING or loop.time() >= deadline:
            return dict(body)
        await asyncio.sleep(POLL_INTERVAL_S)


def finished_result(ctx: Ctx, task_id: str | None, task: Mapping[str, Any]) -> Mapping[str, Any]:
    """A successful task's ``result`` (fail closed when a ``success`` carries none)."""
    raw = task.get("result")
    if not isinstance(raw, Mapping):
        raise MiAssistError(
            "task_unreadable",
            ctx.w("error.task_unreadable", task_id=task_id or "-"),
            fix=ctx.w("error.task_unreadable_fix"),
        )
    return raw


async def file_first_run(
    ctx: Ctx,
    route: Route,
    payload: dict[str, Any],
    *,
    approval_id: str | None,
    ask_again: bool,
    tool: str,
    args: Mapping[str, Any],
    summary: str,
) -> Any:
    """Core's three-step gate, with the repeat-call lookup on the whole filed payload (A43).

    R2 review fix (OR2-int-7), 2026-11-16: first, 003's full request-schema check
    (``vendored.requests.refusals``, A40), as 003's gate runs it: a request miWorkbench's own
    schema refuses is refused here, before anything is looked up or filed, so the operator never
    approves (and spends) a request the route then refuses after the consume."""
    refused = requests.refusals(route, {}, payload)
    if refused:
        raise MiAssistError(
            "invalid_arguments",
            ctx.w("error.request_refused", detail="; ".join(refused)[:400]),
            fix=ctx.w("error.request_refused_fix"),
        )
    filed = canonical_payload(route.method, route.path, {}, {}, payload)
    if approval_id is None and not ask_again:
        found = await pending.open_request(
            ctx.client("miworkbench"),
            str(route.approval_action),
            payload_digest=pending.digest(filed),
        )
        if found is not None:
            approval_id = str(found.get("id"))
    return await ctx.workbench().file_first(
        route,
        path_params={},
        query={},
        body=payload,
        body_param=None,
        approval_id=approval_id,
        person_reason=None,
        tool=tool,
        args=args,
        summary=summary,
    )


def proposed_name(feature: Mapping[str, Any], direction: str) -> str:
    """A cluster name the save accepts (1-120 characters), from the feature's label or id."""
    base = re.sub(r"[^a-z0-9]+", "-", str(feature.get("label") or "").lower()).strip("-")
    base = base or f"feature-{feature.get('feature_id')}"
    return f"{base[:100]}-{'less' if direction == 'less' else 'more'}"


def _approval_state(approval: Mapping[str, Any], waiting: str) -> str:
    status = approval.get("status")
    if status in ("rejected", "expired", "failed"):
        return str(status)
    if status == "executed":
        return "failed"  # the id was used and nothing is running: start again (approval_spent)
    return waiting


# -- try -------------------------------------------------------------------------------------------


@dataclass
class TryArgs:
    feature: str
    prompt: str
    direction: str = "more"
    strengths: list[float] | None = None
    approval_id: str | None = None
    task_id: str | None = None
    ask_again: bool = False


def sweep_outcome(
    ctx: Ctx, task: Mapping[str, Any], base: dict[str, Any], f: Mapping[str, Any], direction: str
) -> Outcome:
    status, error = task_status(ctx, base.get("task_id"), task)
    if status in TASK_FAILED:
        raise MiAssistError(
            "sweep_failed",
            ctx.w("error.sweep_failed", reason=str(error or status)[:200]),
            next=[
                step(
                    "miassist_steering_try",
                    {"feature": f["feature_id"], "ask_again": True},
                    ctx.w("try.again"),
                )
            ],
        )
    if status in TASK_RUNNING:
        return Outcome(
            "sweeping",
            {**base, "swept": False},
            waiting=[
                {"kind": "gpu", "detail": ctx.w("wait.sweeping", task_id=base.get("task_id"))}
            ],
        )
    # StrengthSweepResponse (schemas/steering.py:282-308): unsteered {text}, results [{strength, text}]
    result = finished_result(ctx, base.get("task_id"), task)
    baseline = result.get("unsteered")
    unsteered = baseline.get("text") if isinstance(baseline, Mapping) else None
    pairs = []
    for row in result.get("results") or []:
        if isinstance(row, Mapping):
            text = row.get("text")
            pairs.append((float(row.get("strength", 0.0)), text if isinstance(text, str) else ""))
    verdict = fluency.verdict(unsteered if isinstance(unsteered, str) else None, pairs)
    fields = {
        **base,
        "swept": True,
        "unsteered": verdict.unsteered,
        "results": verdict.rows,
        "usable_strength": verdict.usable,
        "first_collapse": verdict.first_collapse,
    }
    lines = [ctx.w("verdict.rule")]
    lines += [
        ctx.w(
            "verdict.row",
            strength=r["strength"],
            ttr=r["ttr"],
            state=ctx.w("verdict.collapsed" if r["collapsed"] else "verdict.fluent"),
        )
        for r in verdict.rows
    ]
    if verdict.usable is None:
        lines.append(ctx.w("verdict.none_fluent"))
        nxt = [
            step(
                "miassist_steering_try",
                {
                    "feature": f["feature_id"],
                    "strengths": strengths.gentle_strengths(
                        f.get("max_activation"), "less" if direction == "less" else "more"
                    ),
                },
                ctx.w("verdict.try_gentler"),
            )
        ]
    else:
        lines.append(ctx.w("verdict.usable", strength=verdict.usable, label=f.get("label") or "-"))
        nxt = [
            step(
                "miassist_steering_save",
                {
                    # R3 review fix (OR3-int-7), 2026-11-16: a name the save accepts (min 1).
                    "name": proposed_name(f, direction),
                    "features": [{"feature": f["feature_id"], "strength": verdict.usable}],
                },
                ctx.w("verdict.save"),
            )
        ]
    fields["summary_lines"] = lines
    return Outcome("swept", fields, next_steps=nxt)


async def converge_try(ctx: Ctx, a: TryArgs) -> Outcome:
    f = await feature_facts(ctx, a.feature)
    base: dict[str, Any] = {"feature_id": a.feature, "swept": False}
    if a.task_id:
        base["task_id"] = a.task_id
        return sweep_outcome(ctx, await poll_task(ctx, a.task_id), base, f, a.direction)
    if a.strengths is not None:
        values = [round(float(x), 2) for x in a.strengths]
    else:
        try:
            values = strengths.default_strengths(
                f.get("max_activation"), "less" if a.direction == "less" else "more"
            )
        except strengths.NoRealMaxActivation:
            raise MiAssistError(
                "no_real_max_activation",
                ctx.w("error.no_max"),
                fix=ctx.w("error.no_max_fix"),
            ) from None
    payload: dict[str, Any] = {
        "sae_id": f["sae_id"],
        "prompt": a.prompt,
        "feature_idx": f["neuron_index"],
        "layer": f["layer"],
        "strength_values": values,
        "generation_params": dict(GENERATION),
        "gpu": "auto",
    }
    if f.get("model_id"):
        payload["model_id"] = f["model_id"]
    route = gpu_route(ctx, st.SWEEP_ID)
    args = {
        "feature": a.feature,
        "prompt": a.prompt,
        "direction": a.direction,
        **({"strengths": values} if a.strengths else {}),
    }
    summary = ctx.w(
        "approval.sweep",
        label=f.get("label") or f.get("neuron_index"),
        n=len(values),
        model=f.get("model_id") or "-",
    )
    answer = await file_first_run(
        ctx,
        route,
        payload,
        approval_id=a.approval_id,
        ask_again=a.ask_again,
        tool="miassist_steering_try",
        args=args,
        summary=summary,
    )
    base["strengths"] = values
    if isinstance(answer, Pending):
        approval = dict(answer.approval)
        state = _approval_state(approval, "sweep_waiting")
        out = Outcome(state, base, approval=approval)
        if state == "sweep_waiting":
            out.waiting = [
                {
                    "kind": "approval",
                    "detail": ctx.w("wait.approval_wb", approval_id=approval["id"]),
                    "approval": approval,
                }
            ]
        else:
            out.next_steps = [
                step("miassist_steering_try", {**args, "ask_again": True}, ctx.w("try.again"))
            ]
        return out
    if isinstance(answer, Unavailable):
        raise Down("miworkbench", answer.reason)
    if not isinstance(answer, Resource) or not isinstance(answer.body, Mapping):
        if isinstance(answer, AppError):
            raise MiAssistError(answer.code, answer.message or answer.code)
        raise MiAssistError("miworkbench.app_error", "unexpected answer")
    task_id = str(answer.body.get("task_id"))
    base["task_id"] = task_id
    out = sweep_outcome(ctx, await poll_task(ctx, task_id), base, f, a.direction)
    if out.state == "sweeping":
        out.next_steps = [
            step(
                "miassist_steering_try",
                {"feature": a.feature, "prompt": a.prompt, "task_id": task_id},
                ctx.w("try.read_later"),
            )
        ]
    return out


# -- save ------------------------------------------------------------------------------------------


def _applied_matches(
    result: Mapping[str, Any], facts: Sequence[tuple[Mapping[str, Any], float]]
) -> bool:
    """The combined task steered exactly these members: the same SAE and the same
    ``(feature_idx, layer, strength)`` set (``CombinedFeatureApplied``)."""
    if result.get("sae_id") != facts[0][0]["sae_id"]:
        return False
    applied = result.get("features_applied")
    if not isinstance(applied, list):
        return False
    got = {
        (row.get("feature_idx"), row.get("layer"), round(float(row.get("strength", 0.0)), 2))
        for row in applied
        if isinstance(row, Mapping)
    }
    want = {(f["neuron_index"], f["layer"], s) for f, s in facts}
    return len(applied) == len(facts) and got == want


@dataclass
class SaveArgs:
    name: str
    features: list[dict[str, Any]]
    prompt: str | None = None
    narrative: str | None = None
    approval_id: str | None = None
    task_id: str | None = None
    ask_again: bool = False


async def converge_save(ctx: Ctx, a: SaveArgs) -> Outcome:
    wb = ctx.client("miworkbench")
    for item in items(await get(wb, st.CLUSTER_PROFILES_LIST, params={"limit": 100}), "profiles"):
        if item.get("name") == a.name:
            return Outcome(
                "saved",
                {
                    "profile_id": item.get("id"),
                    "name": a.name,
                    "budget": dict(BUDGET),
                    "members": item.get("members") or [],
                },
                subject=a.name,
            )
    facts = []
    for entry in a.features:
        f = await feature_facts(ctx, str(entry["feature"]))
        if entry.get("strength") is None:
            raise MiAssistError(
                "needs_choice", ctx.w("error.needs_strength"), fix=ctx.w("error.needs_strength_fix")
            )
        facts.append((f, round(float(entry["strength"]), 2)))
    saes = {f["sae_id"] for f, _ in facts}
    if len(saes) != 1:
        raise MiAssistError("needs_choice", ctx.w("error.one_sae"))
    combined: dict[str, Any] | None = None
    if len(facts) > 1:
        if not a.prompt:
            raise MiAssistError("needs_choice", ctx.w("error.needs_prompt"))
        payload = {
            "sae_id": facts[0][0]["sae_id"],
            "prompt": a.prompt,
            "selected_features": [
                {"feature_idx": f["neuron_index"], "layer": f["layer"], "strength": s}
                for f, s in facts
            ],
            "generation_params": dict(GENERATION),
            "include_baseline": True,
            "gpu": "auto",
        }
        route = gpu_route(ctx, st.COMBINED_ID)
        args = {"name": a.name, "features": a.features, "prompt": a.prompt}
        if a.task_id:
            task = await poll_task(ctx, a.task_id)
        else:
            answer = await file_first_run(
                ctx,
                route,
                payload,
                approval_id=a.approval_id,
                ask_again=a.ask_again,
                tool="miassist_steering_save",
                args=args,
                summary=ctx.w("approval.combined", n=len(facts)),
            )
            if isinstance(answer, Pending):
                approval = dict(answer.approval)
                state = _approval_state(approval, "combined_waiting")
                out = Outcome(
                    state,
                    {"name": a.name, "members": [], "budget": dict(BUDGET)},
                    approval=approval,
                )
                if state == "combined_waiting":
                    out.waiting = [
                        {
                            "kind": "approval",
                            "detail": ctx.w("wait.approval_wb", approval_id=approval["id"]),
                            "approval": approval,
                        }
                    ]
                return out
            if not isinstance(answer, Resource) or not isinstance(answer.body, Mapping):
                raise MiAssistError("miworkbench.app_error", "unexpected answer")
            task = await poll_task(ctx, str(answer.body.get("task_id")))
            a.task_id = str(answer.body.get("task_id"))
        status, error = task_status(ctx, a.task_id, task)
        if status in TASK_FAILED:
            raise MiAssistError(
                "combined_failed",
                ctx.w("error.sweep_failed", reason=str(error or status)[:200]),
            )
        if status in TASK_RUNNING:
            return Outcome(
                "combining",
                {"name": a.name, "task_id": a.task_id, "members": [], "budget": dict(BUDGET)},
                waiting=[{"kind": "gpu", "detail": ctx.w("wait.sweeping", task_id=a.task_id)}],
            )
        # CombinedSteeringResponse (schemas/steering.py:523-565): combined_output and the
        # features_applied it steered with (R1 review fixes OR1-pb-3 and OR1-pb-16, 2026-11-16).
        result = finished_result(ctx, a.task_id, task)
        text = result.get("combined_output")
        if not isinstance(text, str):
            raise MiAssistError(
                "task_unreadable",
                ctx.w("error.task_unreadable", task_id=a.task_id or "-"),
                fix=ctx.w("error.task_unreadable_fix"),
            )
        if not _applied_matches(result, facts):
            raise MiAssistError(
                "combined_mismatch",
                ctx.w("error.combined_mismatch", task_id=a.task_id or "-"),
                fix=ctx.w("error.combined_mismatch_fix"),
            )
        score = fluency.ttr(text)
        combined = {"ttr": score, "fluent": not fluency.collapsed(text)}
        if not combined["fluent"]:
            raise MiAssistError(
                "combined_not_fluent", ctx.w("error.combined_not_fluent", ttr=score)
            )
    first = facts[0][0]
    body: dict[str, Any] = {
        "name": a.name,
        "sae_id": first["sae_id"],
        "members": [
            {
                "feature_idx": f["neuron_index"],
                "strength": s,
                "sign": -1 if s < 0 else 1,
                **({"label": f["label"]} if f.get("label") else {}),
            }
            for f, s in facts
        ],
        "budget": dict(BUDGET),
    }
    if first.get("model_id"):
        body["model_id"] = first["model_id"]
    if a.narrative:
        body["narrative"] = a.narrative
    answer = await wb.call(st.CLUSTER_PROFILES, json=body)
    if isinstance(answer, Unavailable):
        raise Down("miworkbench", answer.reason)
    if not isinstance(answer, Resource) or not isinstance(answer.body, Mapping):
        if isinstance(answer, AppError):
            raise MiAssistError(answer.code, answer.message or answer.code)
        raise MiAssistError("miworkbench.app_error", "unexpected answer")
    profile_id = answer.body.get("id") or answer.body.get("profile_id")
    fields = {
        "profile_id": profile_id,
        "name": a.name,
        "members": body["members"],
        "budget": dict(BUDGET),
    }
    if combined is not None:
        fields["combined_check"] = combined
    # R3 review fix (OR3-int-7): the summary's {name} slot ("The cluster - is saved." before)
    return Outcome("saved", fields, subject=a.name, slots={"name": a.name})


# -- serve -----------------------------------------------------------------------------------------


@dataclass
class ServeArgs:
    cluster: str | None = None
    circuit: str | None = None
    hub_repo: str | None = None
    prompt: str | None = None
    ask_again: bool = False


def _named(rows: Sequence[Mapping[str, Any]], ref: str) -> Mapping[str, Any] | None:
    """A row by id or name; a Hub-imported cluster by its ``hub_ref.repo_id``
    (miServer ``cluster_hub_service.py:307``)."""
    for row in rows:
        hub = row.get("hub_ref")
        if ref in (row.get("id"), row.get("name")) or (
            isinstance(hub, Mapping) and hub.get("repo_id") == ref
        ):
            return row
    return None


def _conflict(answer: Any) -> bool:
    """miServer's name conflict under ``on_conflict=fail``: 422 ``VALIDATION_ERROR`` "A profile /
    circuit named '...' already exists" (``cluster_service.py:402-406``, ``circuit_service.py:
    1572-1578``; ``core/errors.py:638-642``), never 409 (R1 review fix OR1-pb-9, 2026-11-16)."""
    return (
        isinstance(answer, AppError)
        and answer.status == 422
        and "already exists" in (answer.message or "")
    )


async def _import_cluster(ctx: Ctx, doc: Any, name: str | None) -> dict[str, Any]:
    """Import one cluster definition (never active) and read the imported cluster back.

    ``POST /api/clusters/import`` answers ``ClusterImportResult`` ``{results: [{name, status,
    profile_id}], imported, blocked, errors}`` (``api/schemas/cluster.py:170-184``), never the
    cluster: the cluster (model, SAE, members) is read from ``GET /api/clusters`` by
    ``profile_id`` (R1 review fix OR1-pb-4a, 2026-11-16)."""
    sv = ctx.client("miserver")
    answer = await sv.call(st.CLUSTERS_IMPORT, params={"on_conflict": "fail"}, json=doc)
    if isinstance(answer, Unavailable):
        raise Down("miserver", answer.reason)
    if _conflict(answer) and name:
        found = _named(items(await get(sv, "miserver.list_clusters"), "clusters"), name)
        if found is not None:
            return dict(found)
    if isinstance(answer, AppError):
        raise MiAssistError(answer.code, answer.message or answer.code)
    body = answer.body if isinstance(answer, Resource) else None
    data = body.get("data") if isinstance(body, Mapping) else None
    results = data.get("results") if isinstance(data, Mapping) else None
    first = results[0] if isinstance(results, list) and results else None
    if not isinstance(first, Mapping):
        raise MiAssistError("miserver.app_error", "miServer's import answer had no result")
    if first.get("status") not in ("imported", "imported_unbound") or not first.get("profile_id"):
        raise MiAssistError(
            "import_refused",
            ctx.w(
                "error.import_refused",
                name=first.get("name") or name or "-",
                reason=str(first.get("error") or first.get("status"))[:200],
            ),
        )
    for row in items(await get(sv, "miserver.list_clusters"), "clusters"):
        if row.get("id") == first["profile_id"]:
            return dict(row)
    raise MiAssistError("miserver.app_error", "the imported cluster was not listed")


async def _import_circuit(ctx: Ctx, doc: Any, name: str | None) -> dict[str, Any]:
    """``POST /api/circuits/import`` answers the circuit itself (``CircuitResponse``)."""
    sv = ctx.client("miserver")
    answer = await sv.call(st.CIRCUITS_IMPORT, params={"on_conflict": "fail"}, json=doc)
    if isinstance(answer, Unavailable):
        raise Down("miserver", answer.reason)
    if _conflict(answer) and name:
        found = _named(items(await get(sv, st.CIRCUITS), "circuits"), name)
        if found is not None:
            return dict(found)
    if isinstance(answer, AppError):
        raise MiAssistError(answer.code, answer.message or answer.code)
    body = answer.body if isinstance(answer, Resource) else None
    data = body.get("data") if isinstance(body, Mapping) else None
    if not isinstance(data, Mapping) or not data.get("id"):
        raise MiAssistError("miserver.app_error", "miServer's circuit import answer had no circuit")
    return dict(data)


def handoff(ctx: Ctx, kind: str, name: str, rung: Any = None) -> str:
    text = ctx.w(
        "handoff.cluster" if kind == "cluster" else "handoff.circuit",
        name=name,
        rung=rung if rung is not None else "-",
    )
    if kind == "circuit" and isinstance(rung, int) and rung < 2:
        text += " " + ctx.w("handoff.below_rung2")
    return text


async def converge_serve(ctx: Ctx, a: ServeArgs) -> Outcome:
    sv = ctx.client("miserver")
    clusters = items(await get(sv, "miserver.list_clusters"), "clusters")
    kind, served, rung = "cluster", None, None
    subject = a.cluster or a.circuit or a.hub_repo or ""
    if a.hub_repo:
        served = _named(clusters, a.hub_repo)
        if served is None:
            detail = ctx.w("wait.hub_import", repo=a.hub_repo)
            return Outcome(
                "awaiting_hub_import",
                {"active": False},
                waiting=[{"kind": "operator_action", "detail": detail}],
                subject=subject,
            )
    elif a.circuit:
        kind = "circuit"
        if not ctx.has("miworkbench"):
            served = _named(items(await get(sv, st.CIRCUITS), "circuits"), a.circuit)
            if served is None:
                raise MiAssistError("circuit_not_found", ctx.w("error.circuit_not_found"))
        else:
            wb = ctx.client("miworkbench")
            circuit = await get(wb, st.CIRCUIT, path_params={"circuit_id": a.circuit})
            if not isinstance(circuit, Mapping):
                raise MiAssistError("circuit_not_found", ctx.w("error.circuit_not_found"))
            rung = circuit.get("rung")
            doc = await get(wb, st.CIRCUIT_EXPORT, path_params={"circuit_id": a.circuit})
            served = await _import_circuit(ctx, doc, circuit.get("name"))
    else:
        assert a.cluster is not None
        served = _named(clusters, a.cluster)
        if served is None and ctx.has("miworkbench"):
            doc = await get(
                ctx.client("miworkbench"),
                st.CLUSTER_PROFILE_EXPORT,
                path_params={"profile_id": a.cluster},
            )
            if doc is not None:
                name = doc.get("name") if isinstance(doc, Mapping) else None
                served = await _import_cluster(ctx, doc, name if isinstance(name, str) else None)
        if served is None:
            raise MiAssistError("cluster_not_found", ctx.w("error.cluster_not_found"))
    served_id = str(served.get("id") or served.get("name") or subject)
    served_name = str(served.get("name") or served_id)
    fields: dict[str, Any] = {
        "active": False,
        ("miserver_circuit_id" if kind == "circuit" else "miserver_cluster_id"): served_id,
    }
    if rung is not None:
        fields["rung"] = rung
    # miServer's detailed health (api/routes/system/health.py:330-372): top-level model_loaded,
    # model_name, sae_attached, sae_ids, and active_profile {id, name} (R1 review fix OR1-pb-4b).
    health = await get(sv, st.HEALTH_DETAILED)
    if not isinstance(health, Mapping):
        raise MiAssistError("miserver.app_error", "miServer's detailed health was unreadable")
    want_model = served.get("model_id")
    model: Mapping[str, Any] | None = None
    if kind == "cluster":
        model = await _served_model(ctx, want_model)
        if model.get("status") != "loaded":
            load = await _model_load(
                ctx,
                int(model["id"]),
                str(want_model),
                a.ask_again,
                loading=model.get("status") == "loading",
            )
            if load is not None:
                load.fields = {**fields, **load.fields}
                load.subject = subject
                return load
    attached = [str(x) for x in health.get("sae_ids") or []] or (
        [str(health["sae_id"])] if health.get("sae_id") else []
    )
    want_sae = served.get("sae_id")
    if health.get("sae_attached") and attached and want_sae and str(want_sae) not in attached:
        raise MiAssistError(
            "sae_mismatch",
            ctx.w("error.sae_mismatch", served=want_sae, attached=", ".join(attached)),
            fix=ctx.w("error.sae_mismatch_fix"),
        )
    profile = health.get("active_profile")
    active_now = profile.get("name") if isinstance(profile, Mapping) else None
    if kind == "circuit":
        rows = await get(sv, st.CIRCUITS_ACTIVE)
        serving = [r for r in (rows if isinstance(rows, list) else []) if isinstance(r, Mapping)]
        is_active = any(r.get("id") == served.get("id") for r in serving)
        active_now = ", ".join(str(r.get("name")) for r in serving) or None
    else:
        is_active = served.get("is_active") is True or (
            isinstance(profile, Mapping) and profile.get("id") == served.get("id")
        )
    if is_active:
        fields["active"] = True
        return Outcome("active", fields, subject=subject, slots={"name": served_name})
    if a.prompt and kind == "cluster":
        fields["trial"] = await _trial(
            ctx, served, served_id, str((model or {}).get("name") or want_model or ""), a.prompt
        )
    fields["replaces"] = active_now
    detail = handoff(ctx, kind, served_name, rung)
    state = (
        "awaiting_activation"
        if (fields.get("trial") or kind == "circuit" or not a.prompt)
        else "imported"
    )
    return Outcome(
        state,
        fields,
        waiting=[{"kind": "operator_action", "detail": detail}],
        subject=subject,
        slots={"name": served_name},
    )


async def _served_model(ctx: Ctx, want: Any) -> Mapping[str, Any]:
    """The miServer model a cluster names: ``ClusterSummary.model_id`` is the definition's
    ``hf_id`` (``cluster_service.py:101``), matched to a downloaded model's ``repo_id`` or
    ``name`` in ``GET /api/models`` (integer ``id``, ``status`` ``loaded`` when resident).
    Fails closed (R1 review fix OR1-pb-4): no model named, or none downloaded, refuses."""
    if not isinstance(want, str) or not want:
        raise MiAssistError(
            "model_unknown", ctx.w("error.model_unknown"), fix=ctx.w("error.model_unknown_fix")
        )
    listed = await get(ctx.client("miserver"), "miserver.list_models")
    for row in listed if isinstance(listed, list) else []:
        if isinstance(row, Mapping) and want in (row.get("repo_id"), row.get("name")):
            return row
    raise MiAssistError(
        "model_not_downloaded",
        ctx.w("error.model_not_downloaded", model=want),
        fix=ctx.w("error.model_not_downloaded_fix", model=want),
    )


async def _model_load(
    ctx: Ctx, model_id: int, label: str, ask_again: bool, *, loading: bool = False
) -> Outcome | None:
    """``POST /api/models/{id}/load`` (an integer id) once; a repeat finds the pending request
    (its stored payload carries ``model_id``, ``approval_gate.py:455-461``), or the approved one
    miServer is running (``executing``; R2 review fix OR2-int-1, 2026-11-16).

    R2 review fix (OR2-int-1), 2026-11-16: a model miServer reports as ``loading``
    (``db/models/model.py:30``) is still waiting on its load: nothing is filed, even with
    ``ask_again`` and even when no request of miAssist's is found (the operator started it)."""
    sv = ctx.client("miserver")
    found = (
        None
        if ask_again
        else await pending.open_request(sv, "model_load", fields={"model_id": model_id})
    )
    if found is None and loading:
        detail = ctx.w("wait.model_loading", model=label)
        return Outcome("model_load_waiting", {}, waiting=[{"kind": "job", "detail": detail}])
    if found is None:
        answer = await sv.call(st.MODEL_LOAD, path_params={"model_id": model_id})
        if isinstance(answer, Unavailable):
            raise Down("miserver", answer.reason)
        if isinstance(answer, Resource):
            return None  # already loaded (or loaded without a gate)
        if not isinstance(answer, Pending):
            if isinstance(answer, AppError):
                raise MiAssistError(answer.code, answer.message or answer.code)
            raise MiAssistError("miserver.app_error", "unexpected answer")
        approval = dict(answer.approval)
    else:
        from miassist.results.approvals import approval_object

        approval = approval_object("miserver", found, style="server_executed", summary="-")
    approval["summary"] = ctx.w("approval.model_load", model=label, approval_id=approval["id"])[
        :500
    ]
    state = (
        "model_load_waiting"
        if approval["status"] in ("pending", "executing")
        else str(approval["status"])
    )
    if state == "executed":
        return None
    if approval["status"] == "executing":
        # R3 review fix (OR3-int-7), 2026-11-16: the operator approved and miServer runs the load;
        # nothing is left to decide, so the wait says it is loading (not "Decide in miServer").
        detail = ctx.w("wait.model_loading", model=label)
        return Outcome(
            "model_load_waiting",
            {},
            waiting=[{"kind": "job", "detail": detail, "approval": approval}],
            approval=approval,
        )
    return Outcome(
        (
            state
            if state in ("model_load_waiting", "rejected", "expired", "failed")
            else "model_load_waiting"
        ),
        {},
        waiting=[
            {
                "kind": "approval",
                "detail": ctx.w("wait.approval_sv", approval_id=approval["id"]),
                "approval": approval,
            }
        ],
        approval=approval,
    )


async def _trial(
    ctx: Ctx, served: Mapping[str, Any], served_id: str, model: str, prompt: str
) -> dict[str, Any]:
    """One bounded trial with the cluster's own features (R1 review fix OR1-pb-5, 2026-11-16).

    ``ClusterSummary.members`` are ``(feature_idx, label, strength)`` triples
    (``api/schemas/cluster.py:203-206``). ``features: []`` would be EXPLICITLY UNSTEERED on miServer
    (``schemas/openai.py:211-238``), so a cluster with no member that maps is REFUSED: an unsteered
    reply is never shown as this cluster's."""
    intensity = float(served.get("intensity", 1.0) or 1.0)
    features = []
    for member in served.get("members") or []:
        if (
            isinstance(member, list | tuple)
            and len(member) == 3
            and isinstance(member[0], int)
            and not isinstance(member[0], bool)
            and isinstance(member[2], int | float)
            and not isinstance(member[2], bool)
        ):
            features.append({"index": member[0], "strength": float(member[2]) * intensity})
    if not features:
        raise MiAssistError("trial_no_features", ctx.w("error.trial_no_features"))
    steering: dict[str, Any] = {"features": features}
    if served.get("sae_id"):
        steering["sae_id"] = served["sae_id"]
    body = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": TRIAL_TOKENS,
        "steering": steering,
    }
    answer = await ctx.client("miserver").call(
        st.CHAT_COMPLETIONS, json=body, floor_scope=served_id
    )
    if isinstance(answer, Unavailable):
        raise Down("miserver", answer.reason)
    if isinstance(answer, AppError):
        if answer.code.endswith("model_not_resident"):
            raise MiAssistError("model_not_resident", ctx.w("error.model_not_resident"))
        raise MiAssistError(answer.code, answer.message or answer.code)
    choices = (
        answer.body.get("choices")
        if isinstance(answer, Resource) and isinstance(answer.body, Mapping)
        else None
    )
    message = (
        choices[0].get("message")
        if isinstance(choices, list) and choices and isinstance(choices[0], Mapping)
        else None
    )
    text = message.get("content") if isinstance(message, Mapping) else None
    return {"excerpt": fluency.excerpt(text if isinstance(text, str) else ""), "clamped": None}
