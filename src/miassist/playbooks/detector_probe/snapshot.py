"""The behaviour's state, read from the installed apps (003 FTDD §2, §6; FPRD FR-003.25, A22).

``read`` runs every read concurrently; an unreachable app contributes ``unavailable`` for its part
only. Every list is reduced HERE to the exact match for a name or id already in the journey (the
key, or an id in the progress record): no other entry of any list is held in the snapshot, so none
can reach a result. Event lists become counts; no event object or text is kept (Q10).
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from miassist.adapters.base import AppError, Resource, Route, Unavailable
from miassist.errors import MiAssistError
from miassist.playbooks.detector_probe import routes as rt
from miassist.playbooks.detector_probe.context import Ctx

EVENT_PAGE = 500
VERDICTS = ("fired", "not_fired", "not_scored")


@dataclass
class Snapshot:
    key: str
    behaviour: dict[str, Any] | None = None
    views: dict[str, dict[str, Any]] = field(default_factory=dict)
    run: dict[str, Any] | None = None
    report: dict[str, Any] | None = None
    approvals: dict[str, dict[str, Any]] = field(default_factory=dict)
    dw_status: dict[str, Any] | None = None
    dw_send: dict[str, Any] | None = None
    sv_probe: dict[str, Any] | None = None
    sv_armed: bool = False
    sv_paused_reason: str | None = None
    sv_event_counts: dict[str, str] | None = None
    unavailable: dict[str, str] = field(default_factory=dict)


async def get(ctx: Ctx, app: str, route: Route, snap: Snapshot, **kw: Any) -> Any:
    """One read: the body, ``None`` for a 404 or a refusal, and ``unavailable`` noted by app."""
    if not ctx.has(app) or app in snap.unavailable:
        return None
    try:
        answer = await ctx.client(app).call(route, **kw)
    except MiAssistError:
        return None
    if isinstance(answer, Unavailable):
        snap.unavailable[app] = answer.reason
        return None
    if isinstance(answer, Resource):
        return answer.body
    if isinstance(answer, AppError):
        return None
    return None


def _data(body: Any) -> Any:
    """miServer wraps answers in ``{"data": ...}``."""
    return body.get("data", body) if isinstance(body, Mapping) else body


def role_of(view: Mapping[str, Any]) -> str:
    """The journey role of a view read whole (``GET /probe-monitors/datasets/{id}``, which carries
    ``distribution``; the behaviour detail's ``view_out`` does not)."""
    role = str(view.get("role") or "")
    if role == "eval":
        out = view.get("distribution") == "out_of_distribution"
        return "ood" if out else "test"
    return role


def selected_probe(run: Mapping[str, Any] | None) -> str | None:
    """The probe a finished run selected: ``selection.selected`` on ``ProbeRunResponse``
    (``probe_monitor_run.record_selection``). R1 review fix (OR1-pb-6), 2026-11-16: the run has no
    ``selected_probe_id`` (only the runs-list summary does)."""
    selection = (run or {}).get("selection")
    found = selection.get("selected") if isinstance(selection, Mapping) else None
    return str(found) if found else None


async def _workbench(ctx: Ctx, snap: Snapshot) -> None:
    detail = await get(ctx, "miworkbench", rt.BEHAVIOUR, snap, path_params={"key": snap.key})
    if not isinstance(detail, Mapping):
        return
    snap.behaviour = {"key": snap.key, "catalogued_in": "miworkbench"}
    inner = detail.get("adopted")
    adopted: Mapping[str, Any] = inner if isinstance(inner, Mapping) else detail
    chosen_views = dict(ctx.chosen.get("views") or {})
    listed = [
        str(view.get("id"))
        for view in adopted.get("views") or []
        if isinstance(view, Mapping)
        and not view.get("archived")
        and (view.get("behaviour") in (None, snap.key) or view.get("id") in chosen_views.values())
    ]
    # R1 review fix (OR1-pb-7), 2026-11-16: each view is read whole, by its id, for the role
    # (distribution), the counts and the archive time the behaviour detail does not carry.
    wanted = list(dict.fromkeys([*listed, *(str(v) for v in chosen_views.values() if v)]))
    whole = await asyncio.gather(
        *(
            get(ctx, "miworkbench", rt.PROBE_VIEW, snap, path_params={"dataset_id": v})
            for v in wanted
        )
    )
    by_id = {v: w for v, w in zip(wanted, whole, strict=True) if isinstance(w, Mapping)}
    for view_id in listed:
        view = by_id.get(view_id)
        if view is None or view.get("archived_at"):
            continue
        snap.views.setdefault(role_of(view), {"id": view_id, "counts": view.get("counts")})
    for role, view_id in chosen_views.items():
        found = by_id.get(str(view_id)) if view_id else None
        if found is not None and found.get("archived_at"):
            continue
        snap.views.setdefault(role, {"id": view_id, "counts": (found or {}).get("counts")})
    runs = [r for r in adopted.get("runs") or [] if isinstance(r, Mapping)]
    run_id = ctx.chosen.get("run_id") or (runs[0].get("id") if runs else None)
    if run_id:
        snap.run = await get(ctx, "miworkbench", rt.RUN, snap, path_params={"run_id": run_id})
    probe_id = ctx.chosen.get("probe_id") or selected_probe(snap.run)
    if probe_id:
        snap.report = await get(
            ctx,
            "miworkbench",
            rt.PROBE_REPORT,
            snap,
            path_params={"probe_id": probe_id},
            params={"detail": "summary"},
        )


async def _approvals(ctx: Ctx, snap: Snapshot) -> None:
    from miassist.adapters.routes import ROUTES

    for kind, approval_id in dict(ctx.chosen.get("approvals") or {}).items():
        if not approval_id:
            continue
        app = "midataworks" if kind == "send" else "miworkbench"
        route = ROUTES.get(f"{app}.get_approval")
        param = "request_id" if app == "miworkbench" else "approval_id"
        body = await get(ctx, app, route, snap, path_params={param: approval_id})
        if isinstance(body, Mapping):
            snap.approvals[kind] = {"id": approval_id, **dict(body)}


async def _dataworks(ctx: Ctx, snap: Snapshot) -> None:
    status = await get(
        ctx, "midataworks", rt.DW_BEHAVIOUR_STATUS, snap, path_params={"key": snap.key}
    )
    if not isinstance(status, Mapping):
        return
    found = status.get("objects")
    objects: Mapping[str, Any] = found if isinstance(found, Mapping) else {}
    nxt = status.get("next") if isinstance(status.get("next"), Mapping) else None
    sends = [s for s in objects.get("detector_sends") or [] if isinstance(s, Mapping)]
    snap.dw_status = {
        "next_step": (nxt or {}).get("step"),
        "next_title": next(
            (
                s.get("title")
                for s in status.get("journey") or []
                if s.get("step") == (nxt or {}).get("step")
            ),
            None,
        ),
        "complete": bool(status.get("complete")),
        "set_ids": [
            s.get("id")
            for s in objects.get("detector_sets") or []
            if isinstance(s, Mapping) and not s.get("archived")
        ],
        "counts": {k: v for k, v in (status.get("counts") or {}).items() if isinstance(v, int)},
    }
    send_id = ctx.chosen.get("send_id") or (sends[0].get("id") if sends else None)
    if send_id:
        send = await get(
            ctx,
            "midataworks",
            rt.DW_DETECTOR_SEND,
            snap,
            path_params={"send_id": send_id},
            params={"detail": "summary"},
        )
        if isinstance(send, Mapping):
            snap.dw_send = {
                "id": send_id,
                "state": send.get("state"),
                "run_request": send.get("run_request"),
                "checks_refused": sum(
                    1
                    for c in send.get("checks") or []
                    if isinstance(c, Mapping) and c.get("outcome") == "refused"
                ),
            }


async def _server(ctx: Ctx, snap: Snapshot) -> None:
    from miassist.adapters.routes import ROUTES

    wanted = ctx.chosen.get("miserver_probe_id")
    if not wanted and ctx.chosen.get("hub_repo"):
        listed = _data(await get(ctx, "miserver", rt.SV_PROBES, snap))
        for item in listed if isinstance(listed, list) else []:
            if isinstance(item, Mapping) and item.get("hf_id") == ctx.chosen["hub_repo"]:
                wanted = str(item.get("id"))
    if not wanted:
        return
    status = _data(await get(ctx, "miserver", ROUTES.get("miserver.probe_status"), snap))
    armed = [p for p in (status or {}).get("armed") or [] if isinstance(p, Mapping)]
    match = next((p for p in armed if p.get("id") == wanted), None)
    snap.sv_probe = {"id": wanted}
    if match is not None:
        snap.sv_armed = True
        reason = match.get("paused_reason")
        snap.sv_paused_reason = str(reason)[:200] if reason else None
        snap.sv_event_counts = await event_counts(ctx, snap, wanted)


async def event_counts(ctx: Ctx, snap: Snapshot, probe_id: str) -> dict[str, str]:
    """Counts per verdict over 24 h (FTID I3): the page length, "500+" when ``meta.next`` is set.
    Only the count leaves this function; the events themselves are dropped here (Q10)."""
    since = (datetime.now(UTC) - timedelta(hours=24)).isoformat()
    out: dict[str, str] = {}
    for verdict in VERDICTS:
        body = await get(
            ctx,
            "miserver",
            rt.SV_PROBE_EVENTS,
            snap,
            params={"probe_id": probe_id, "since": since, "verdict": verdict, "limit": EVENT_PAGE},
        )
        items = body.get("data") if isinstance(body, Mapping) else body
        meta = body.get("meta") if isinstance(body, Mapping) else None
        n = len(items) if isinstance(items, list) else 0
        more = isinstance(meta, Mapping) and bool(meta.get("next"))
        out[verdict] = f"{EVENT_PAGE}+" if more else str(n)
    return out


async def read(ctx: Ctx, key: str) -> Snapshot:
    snap = Snapshot(key=key)
    await asyncio.gather(_workbench(ctx, snap), _dataworks(ctx, snap), _server(ctx, snap))
    await _approvals(ctx, snap)
    if snap.behaviour is None and ctx.chosen.get("catalogued_in") == "miassist":
        snap.behaviour = {"key": key, "catalogued_in": "miassist"}
    if snap.behaviour is None and snap.dw_status is not None:
        snap.behaviour = {"key": key, "catalogued_in": "midataworks"}
    return snap
