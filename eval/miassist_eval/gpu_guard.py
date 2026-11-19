"""The GPU guard, one module with two surface rules (FR-002.11a, FR-002.11b; FTID §3.15; A18, A32,
A38, A41; R1M-6, R2M-14, R3M-3, R3M-4; TD-12).

The guarded list is DERIVED at suite start from Core's vendored copy of 045's
``miworkbench-approval-payload-vectors-v1.json``: one vector per gated ROUTE, each resolved in the
reference OpenAPI to a route template and guarded under the vector's action. The guard is keyed by
``(method, template)``, never by action. No list and no count is written in this package; the only
hand-written part is the partial-arm overlay in ``route_profiles/miworkbench.yaml``.
"""

from __future__ import annotations

import json
import os
import re
from collections import Counter
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from miassist_eval import classes, openapi_ref
from miassist_eval.classes import Refusal

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_VECTORS = REPO_ROOT / "docs" / "schemas" / "miworkbench-approval-payload-vectors-v1.json"
CONSUME = "/api/v1/mcp/approvals/{request_id}/consume"
STATUS_READ = "/api/v1/mcp/approvals/{request_id}"
APPROVAL_HEADER = "X-MiStudio-Approval-Request"
PENDING_HEADER = "X-MiStudio-Approval"
#: The actions the pinned post-A0 baseline miWorkbench image's MCP layer gates with the deployed
#: settings (FR-002.11a): today the five probe actions of ``mcp_approvals.py:108-119``; the steering
#: actions stay out while ``MCP_STEERING_APPROVAL=false`` (``miWorkbench/k8s/base/mcp.yaml:73-74``).
#: Re-read at FTASKS 8.1 against the pinned image's commit and manifest.
BASELINE_MCP_GATED = frozenset(
    {
        "start_probe_training_run",
        "evaluate_probe_monitor",
        "start_probe_judge_run",
        "start_probe_spot_check",
        "recalibrate_probe_monitor",
    }
)
#: R1 review fix (OR1-002-4), 2026-11-16. The steering GPU starts, by verb; every route variant
#: (``/async/<verb>`` and the synchronous ``/<verb>``) is matched, so none is missed (``combined``
#: was). While the vendored vectors do not hold a route, the miAssist surface REFUSES it with
#: ``gpu_list_incomplete`` (never passes, never skips); the baseline treats it as a GPU start (the
#: operator's terminal hold when recording). The refusal lifts by itself, route by route, once Core
#: re-vendors vectors that hold it (045 @ 87e1d5551 holds the three ``/async/`` routes).
STEERING_ACTIONS = {
    "compare": "steer_compare",
    "sweep": "steer_sweep",
    "combined": "steer_combined",
}
STEERING_START = re.compile(r"/api/v1/steering/(?:async/)?(compare|sweep|combined)")
#: The GPU routes each playbook's goal needs before it may be recorded or run on the miAssist
#: surface (hand-written per goal, R1 review fix OR1-002-4). A route here that the derived list
#: does not hold refuses the goal with ``gpu_list_incomplete``.
GOAL_GPU_ROUTES: dict[str, tuple[tuple[str, str], ...]] = {
    "steering": (
        ("POST", "/api/v1/steering/async/compare"),
        ("POST", "/api/v1/steering/async/sweep"),
        ("POST", "/api/v1/steering/async/combined"),
    ),
    "detector-probe": (
        ("POST", "/api/v1/probe-monitors/runs"),
        ("POST", "/api/v1/probe-monitors/probes/{probe_id}/evaluate"),
        ("POST", "/api/v1/probe-monitors/probes/{probe_id}/definition"),
    ),
    "dataset": (),
}
TRUE_SPELLINGS = frozenset({"1", "true", "yes", "on", "t", "y"})
FALSE_SPELLINGS = frozenset({"0", "false", "no", "off", "f", "n"})


def vectors_path() -> Path:
    return Path(os.environ.get("MIASSIST_WB_PAYLOAD_VECTORS", DEFAULT_VECTORS))


@dataclass(frozen=True)
class Arm:
    from_: str
    parse: str
    armed_unless: bool | None = None
    armed_unless_in: tuple[str, ...] = ()


@dataclass(frozen=True)
class GpuStart:
    action: str
    template: str
    method: str
    arm: Arm | None = None


@dataclass
class Req:
    """What the guard reads of a request."""

    method: str
    path: str
    query: Mapping[str, str]
    headers: Mapping[str, str]
    json: Any = None


@dataclass
class RunState:
    approved_reads: dict[str, tuple[str, str, Any]] = field(default_factory=dict)
    used_ids: set[str] = field(default_factory=set)
    consumed: Counter[str] = field(default_factory=Counter)


GpuList = dict[tuple[str, str], GpuStart]


def load(
    refdoc_wb: openapi_ref.RefDoc,
    arms: Mapping[str, Mapping[str, Any]] | None = None,
    path: Path | None = None,
) -> GpuList:
    """The guarded routes, keyed by ``(method, template)``. A missing or unreadable file refuses
    ``gpu_list_missing`` on EVERY surface (R3M-4); never an empty dict."""
    path = path or vectors_path()
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
        vectors = doc["vectors"]
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise Refusal(classes.GPU_LIST_MISSING, f"{path}: {exc}") from exc
    if not vectors:
        raise Refusal(classes.GPU_LIST_MISSING, f"{path}: no vectors")
    arms = dict(arms or {})
    out: GpuList = {}
    for v in vectors:
        method = str(v["method"]).upper()
        req_path = str(v.get("request", {}).get("path") or v.get("path"))
        route = openapi_ref.resolve(refdoc_wb, method, req_path)
        if route is None:
            raise ValueError(f"vector {v.get('action')} {method} {req_path}: not in the reference")
        key = (method, route.template)
        spec = arms.get(f"{method} {route.template}")
        arm = None
        if spec is not None:
            arm = Arm(
                from_=str(spec["from"]),
                parse=str(spec["parse"]),
                armed_unless=spec.get("armed_unless"),
                armed_unless_in=tuple(spec.get("armed_unless_in", ())),
            )
        out[key] = GpuStart(
            action=str(v["action"]), template=route.template, method=method, arm=arm
        )
    unknown = sorted(set(arms) - {f"{m} {t}" for m, t in out})
    if unknown:
        raise ValueError(f"gpu_arms name routes no vector has: {unknown}")
    return out


def _read_value(arm: Arm, req: Req) -> tuple[bool, Any]:
    where, _, name = arm.from_.partition(".")
    if where == "query":
        return (name in req.query, req.query.get(name))
    if isinstance(req.json, Mapping):
        return (name in req.json, req.json.get(name))
    return (False, None)


def arm_holds(arm: Arm, req: Req) -> bool:
    """A41: read where the route reads it, parsed the route's way; fail closed."""
    present, value = _read_value(arm, req)
    if arm.parse == "fastapi_bool":
        if not present:
            return False  # the route's default (False)
        text = str(value).lower() if not isinstance(value, bool) else str(value).lower()
        if text in TRUE_SPELLINGS:
            return True
        if text in FALSE_SPELLINGS:
            return False
        return True  # unparseable: armed
    if arm.parse == "literal":
        return not (present and value in arm.armed_unless_in)
    return True


def approval_id(req: Req) -> str | None:
    rid = _header(req.headers, APPROVAL_HEADER)
    if rid:
        return rid
    if isinstance(req.json, Mapping):
        value = req.json.get("approval_request_id")
        return str(value) if value else None
    return None  # a bare-array or absent body: never searched (A37)


def _header(headers: Mapping[str, str], name: str) -> str | None:
    for k, v in headers.items():
        if k.lower() == name.lower():
            return v
    return None


UNGATED = classes.UNGATED_GPU_START
Hold = Callable[[GpuStart, Req], bool]


def pending_start(method: str, template: str) -> GpuStart | None:
    """A steering GPU start by its route (OR1-002-4), whether or not the vectors hold it."""
    match = STEERING_START.fullmatch(template)
    if method != "POST" or match is None:
        return None
    return GpuStart(action=STEERING_ACTIONS[match.group(1)], template=template, method=method)


def incomplete(gpu: GpuList, refdoc_wb: openapi_ref.RefDoc) -> list[str]:
    """Every steering GPU start in the reference that the derived list does not hold."""
    return sorted(
        r.key
        for r in refdoc_wb.routes
        if pending_start(r.method, r.template) is not None and (r.method, r.template) not in gpu
    )


def goal_incomplete(playbook_id: str, gpu: GpuList) -> list[str]:
    """The GPU routes a goal needs that the derived list does not hold (empty when complete). An
    unknown playbook is refused too: its routes are not known."""
    if playbook_id not in GOAL_GPU_ROUTES:
        return [f"playbook {playbook_id}: its GPU routes are not listed (GOAL_GPU_ROUTES)"]
    return [f"{m} {t}" for m, t in GOAL_GPU_ROUTES[playbook_id] if (m, t) not in gpu]


def refuse_incomplete_goal(playbook_id: str, gpu: GpuList, surface: str) -> None:
    """``gpu_list_incomplete`` for a goal on the miAssist surface whose GPU routes are not all
    guarded (OR1-002-4): its suite records zero runs and ``record`` records nothing."""
    if surface != "miassist":
        return
    missing = goal_incomplete(playbook_id, gpu)
    if missing:
        raise Refusal(
            classes.GPU_LIST_INCOMPLETE,
            f"{playbook_id}: not in the vendored vectors yet: {missing} (Core re-vendors, NEEDS)",
        )


def check(
    state: RunState,
    gpu: GpuList,
    surface: str,
    app: str,
    route: openapi_ref.Route,
    req: Req,
    hold: Hold | None = None,
) -> Refusal | None:
    """None to let the request through; a Refusal otherwise. ``hold`` is the recorder's terminal
    prompt on the baseline (FR-002.11b); replay passes None and never holds."""
    if app != "miworkbench":
        return None
    if surface == "miassist" and route.method == "POST" and route.template == CONSUME:
        return Refusal(classes.FORBIDDEN_ROUTE, "miAssist never calls /consume (A18)")
    start = gpu.get((route.method, route.template))
    if start is None:
        start = pending_start(route.method, route.template)
        if start is None:
            return None
        if surface == "miassist":
            return Refusal(
                classes.GPU_LIST_INCOMPLETE,
                f"{route.key}: a GPU start the vendored vectors do not hold yet (OR1-002-4)",
            )
    if start.arm is not None and not arm_holds(start.arm, req):
        return None
    if surface == "miassist":
        rid = approval_id(req)
        if rid is None or rid not in state.approved_reads:
            return Refusal(classes.UNGATED_GPU_START, f"{route.key}: no approved id")
        tool, requested_by, approved_route = state.approved_reads[rid]
        if (tool, requested_by) != (start.action, "miassist"):
            return Refusal(classes.UNGATED_GPU_START, f"{route.key}: id approved for {tool}")
        if approved_route is None:
            # R1 review fix (OR1-002-6), 2026-11-16: an approval whose payload names no route
            # binds nothing (A38); it never starts GPU work.
            return Refusal(UNGATED, f"{route.key}: id approved with no route (no _route)")
        if approved_route != (
            route.method,
            route.template,
            tuple(sorted(route.params(req.path).items())),
        ):
            return Refusal(classes.UNGATED_GPU_START, f"{route.key}: id approved for another route")
        if rid in state.used_ids:
            return Refusal(classes.UNGATED_GPU_START, f"{route.key}: id already used")
        state.used_ids.add(rid)
        return None
    if start.action in BASELINE_MCP_GATED:
        if state.consumed[start.action] > 0:
            state.consumed[start.action] -= 1
            return None
        return Refusal(classes.UNGATED_GPU_START, f"{route.key}: no consume for {start.action}")
    if hold is None:
        return None  # replay: no GPU, no hold
    if hold(start, req):
        return None
    return Refusal(classes.UNGATED_GPU_START, f"{route.key}: the operator did not allow it")


def _approved_route(payload: Any, refdoc_wb: openapi_ref.RefDoc | None) -> Any:
    """The route an approved row's flat payload names (A38), as ``(method, template, params)``."""
    if not isinstance(payload, Mapping) or "_route" not in payload:
        return None
    method = str(payload.get("_method", "POST")).upper()
    template = str(payload["_route"])
    params = {
        k: str(v)
        for k, v in payload.items()
        if not str(k).startswith("_") and "{" + str(k) + "}" in template
    }
    return (method, template, tuple(sorted(params.items())))


def observe(
    state: RunState,
    gpu: GpuList,
    surface: str,
    app: str,
    route: openapi_ref.Route,
    req: Req,
    status: int,
    headers: Mapping[str, str],
    body: Any,
) -> str | None:
    """Update the state from an answer; ``gpu_list_drift`` when an unlisted route answers 202
    pending on the miAssist surface."""
    if app != "miworkbench":
        return None
    if route.method == "GET" and route.template == STATUS_READ and isinstance(body, Mapping):
        if status == 200 and body.get("status") == "approved":
            rid = str(body.get("id") or route.params(req.path).get("request_id"))
            state.approved_reads[rid] = (
                str(body.get("tool_name")),
                str(body.get("requested_by")),
                _approved_route(body.get("payload"), None),
            )
    if route.method == "POST" and route.template == CONSUME and status == 200:
        if isinstance(body, Mapping) and body.get("tool_name"):
            state.consumed[str(body["tool_name"])] += 1
    if (
        surface == "miassist"
        and status == 202
        and (route.method, route.template) not in gpu
        and str(_header(headers, PENDING_HEADER) or "").lower() == "pending"
    ):
        return classes.GPU_LIST_DRIFT
    return None
