"""miServer's conditional gates and miForge's marked routes are never registered (A19, R2M-10,
R2M-12; 001 FTASKS 4.4: test_miserver_conditional, test_miforge_marked_routes)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from miassist.adapters.base import GateClass, Route
from miassist.adapters.routes import (
    MISERVER_CONDITIONAL_GATES,
    NEVER_ROUTES,
    ROUTES,
    RouteRegistry,
    UnknownGate,
    classify_marker,
)

OPENAPI = Path(__file__).resolve().parents[1] / "fixtures" / "openapi"


def test_miserver_conditional_literal_paths() -> None:
    assert MISERVER_CONDITIONAL_GATES == {
        ("PUT", "/api/environment"),
        ("PUT", "/api/environment/{key}"),
        ("DELETE", "/api/environment/{key}"),
        ("POST", "/api/rule-sets/import"),
    }


@pytest.mark.parametrize(("method", "path"), sorted(MISERVER_CONDITIONAL_GATES))
def test_miserver_conditional_refused_at_registration(method: str, path: str) -> None:
    route = Route("miserver.conditional", "miserver", method, path, GateClass.APP_GATED, "x")
    with pytest.raises(UnknownGate):
        RouteRegistry((route,))
    with pytest.raises(UnknownGate):
        classify_marker("miserver", method, path, {"x-approval-action": "telemetry_write"})


def test_miserver_model_load_registers_cleanly() -> None:
    marked = classify_marker(
        "miserver", "POST", "/api/models/{model_id}/load", {"x-approval-action": "model_load"}
    )
    assert marked is GateClass.APP_GATED


def test_miforge_marked_routes() -> None:
    rows = json.loads((OPENAPI / "miforge.index.json").read_text())["routes"]
    marked = [(r["method"], r["path"]) for r in rows if "x-approval-action" in r]
    for row in rows:
        if "x-approval-action" in row:
            with pytest.raises(UnknownGate):
                classify_marker("miforge", row["method"], row["path"], row)
    registered = {(r.method, r.path) for r in ROUTES.for_app("miforge")}
    assert not registered & set(marked), "a marked miForge route is registered (R2M-10)"


#: miForge's conditionally gated WSP starts (018 review record ``0xcc/reviews/018_miforge_routes.md``):
#: an agent's inspect through a LOCAL endpoint runs with no approval (the protocol test is always
#: an inspect); an external endpoint waits as ``wsp_session_external``, and a run start's other
#: kinds on a local endpoint as ``wsp_session`` (miForge ``backend/src/services/approval_gates.py``
#: ``wsp_run_needs_approval``, ``wsp_protocol_test_needs_approval``). miForge publishes only ``x-approval-action: wsp_session`` and no
#: ``x-approval-when``, so miAssist cannot state the condition: both stay unregistrable (R2M-10).
MIFORGE_CONDITIONAL_WSP_STARTS = (
    ("POST", "/api/v1/wsp/runs"),
    ("POST", "/api/v1/wsp/endpoints/{endpoint_id}/protocol-test"),
)


@pytest.mark.parametrize(("method", "path"), MIFORGE_CONDITIONAL_WSP_STARTS)
def test_miforge_conditional_wsp_starts_stay_marked_and_unregistered(
    method: str, path: str
) -> None:
    """Named, so ``test_miforge_marked_routes`` cannot pass vacuously for these two: each is in the
    pinned index WITH its marker (a pin that lost it would let the route be registered)."""
    rows = json.loads((OPENAPI / "miforge.index.json").read_text())["routes"]
    row = next((r for r in rows if (r["method"], r["path"]) == (method, path)), None)
    assert row is not None, f"{method} {path} is missing from miForge's pinned route index"
    assert row.get("x-approval-action") == "wsp_session", row
    assert row.get("x-approval-escalation") == "wsp_session_external", row
    assert "x-approval-when" not in row, "miForge now states its condition: reclassify (A19)"
    assert (method, path) not in {(r.method, r.path) for r in ROUTES.for_app("miforge")}


#: miForge's escalating gates at the pinned commit (FU-10): a call to each waits as the first
#: action, or as the second when the request asks for it. Cited from miForge ``backend/src`` at
#: ``cfc9baf`` (``requires_approval_when_agent(..., escalate=...)``): ``api/v1/endpoints/chains.py:89-94``,
#: ``runs_acquisition.py:165-170`` (``POST /runs``), ``runs_loop.py:110-115`` (``POST /runs/define``),
#: ``wsp_endpoints.py:146-152`` and ``wsp_runs.py:40-46``; ``api/agent_origin.py:402-425``
#: (``mark_gated_routes``) publishes the second as ``x-approval-escalation``.
MIFORGE_ESCALATIONS = {
    ("POST", "/api/v1/chains"): ("gpu_start", "hotupdate_attach"),
    ("POST", "/api/v1/runs"): ("gpu_start", "hotupdate_attach"),
    ("POST", "/api/v1/runs/define"): ("gpu_start", "hotupdate_attach"),
    ("POST", "/api/v1/wsp/endpoints/{endpoint_id}/protocol-test"): (
        "wsp_session",
        "wsp_session_external",
    ),
    ("POST", "/api/v1/wsp/runs"): ("wsp_session", "wsp_session_external"),
}


def test_miforge_route_index_keeps_the_escalation_marker() -> None:
    """FU-10 (OVN-miassist-1124-4): the GENERATED index (``scripts.snapshot_openapi.route_index``)
    keeps ``x-approval-escalation``; a generator that drops it regenerates an index this fails."""
    rows = json.loads((OPENAPI / "miforge.index.json").read_text())["routes"]
    escalating = {
        (r["method"], r["path"]): (r["x-approval-action"], r["x-approval-escalation"])
        for r in rows
        if "x-approval-escalation" in r
    }
    assert escalating == MIFORGE_ESCALATIONS
    registered = {(r.method, r.path) for r in ROUTES.for_app("miforge")}
    for (method, path), (action, escalation) in MIFORGE_ESCALATIONS.items():
        row = next(r for r in rows if (r["method"], r["path"]) == (method, path))
        with pytest.raises(UnknownGate, match="x-approval-escalation") as refused:
            classify_marker("miforge", method, path, row)
        assert repr(escalation) in str(refused.value) and repr(action) in str(refused.value)
        assert (method, path) not in registered


@pytest.mark.parametrize(
    ("app", "op"),
    [
        ("miserver", {"x-approval-action": "model_load", "x-approval-escalation": "model_swap"}),
        (
            "midataworks",
            {
                "x-approval-action": "publish",
                "x-approval-when": "always",
                "x-approval-escalation": "publish_private",
            },
        ),
    ],
)
def test_an_escalating_marker_is_refused_for_every_app(app: str, op: dict[str, str]) -> None:
    """Without the escalation these two classify as ``app_gated``; with it the action a call waits
    as is chosen per request, so no gate class fits (FU-10)."""
    plain = {k: v for k, v in op.items() if k != "x-approval-escalation"}
    assert classify_marker(app, "POST", "/api/fixture", plain) is GateClass.APP_GATED
    with pytest.raises(UnknownGate, match="x-approval-escalation"):
        classify_marker(app, "POST", "/api/fixture", op)


def test_miforge_endpoint_proposal_stays_marked_and_never_registered() -> None:
    """``POST /api/v1/wsp/endpoints`` (1124 re-pin, ``0xcc/reviews/018_miforge_routes_1124.md``):
    since miForge ``d80e333`` an agent's call is always gated as ``wsp_endpoint_register`` (no
    ``when``; a key, a price or an external URL is refused before filing) and miForge runs it once
    approved. It is BOTH a never-route and marked, so either guard alone still refuses it; this
    test fails if the pin loses the marker or the never-route stops matching."""
    method, path = "POST", "/api/v1/wsp/endpoints"
    rows = json.loads((OPENAPI / "miforge.index.json").read_text())["routes"]
    row = next((r for r in rows if (r["method"], r["path"]) == (method, path)), None)
    assert row is not None, f"{method} {path} is missing from miForge's pinned route index"
    assert row.get("x-approval-action") == "wsp_endpoint_register", row
    assert "x-approval-when" not in row, "miForge now states a condition: reclassify (A19)"
    matched = [n.id for n in NEVER_ROUTES if n.matches("miforge", method, path)]
    assert matched == ["miforge.wsp_endpoint_register"], matched
    assert (method, path) not in {(r.method, r.path) for r in ROUTES.for_app("miforge")}


#: miForge's UNMARKED writes added after 018-P2 that miAssist must not register (1124 re-pin):
#: ``evaluate`` is an ungated, idempotent write by design (miForge ``wsp_candidates.py``, PF-12)
#: that spends a held-out set's capped use count and calls miWorkbench's scorer. As an ungated
#: write it needs a write-floor entry (A25) and none of the fourteen fits; widening the floor is
#: the operator's. Unmarked, so the marker rule cannot refuse it: this list does.
MIFORGE_UNMARKED_UNREGISTRABLE = (("POST", "/api/v1/wsp/candidates/{candidate_id}/evaluate"),)


@pytest.mark.parametrize(("method", "path"), MIFORGE_UNMARKED_UNREGISTRABLE)
def test_miforge_unmarked_wsp_writes_stay_unregistered(method: str, path: str) -> None:
    rows = json.loads((OPENAPI / "miforge.index.json").read_text())["routes"]
    row = next((r for r in rows if (r["method"], r["path"]) == (method, path)), None)
    assert row is not None, f"{method} {path} is missing from miForge's pinned route index"
    assert "x-approval-action" not in row, "miForge now gates it: reclassify (R2M-10)"
    assert (method, path) not in {(r.method, r.path) for r in ROUTES.for_app("miforge")}


#: miWorkbench's 044 WSP routes, gated for every agent since `4716e429b` (044's approval-gated
#: agent path; re-pinned 2026-11-24, US Eastern): the held-out capture (a GPU job) and the
#: candidate import (a new rung-0 probe). miAssist offers no WSP playbook, so it registers neither;
#: offering them is the operator's decision. Were one registered it would have to be `app_gated` +
#: `file_first` with its action in `CALLER_TOOLS` (`test_miworkbench_gpu_routes_are_file_first`).
MIWORKBENCH_WSP_GATED = (
    ("POST", "/api/v1/wsp/captures", "capture_wsp_heldout"),
    ("POST", "/api/v1/wsp/candidates/import", "import_wsp_candidate"),
)


@pytest.mark.parametrize(("method", "path", "action"), MIWORKBENCH_WSP_GATED)
def test_miworkbench_wsp_gated_routes_are_pinned_and_never_registered(
    method: str, path: str, action: str
) -> None:
    snapshot = json.loads((OPENAPI / "miworkbench.json").read_text())
    assert [method, path, action] in snapshot["gated_routes"], "re-pin miWorkbench (044's WSP gate)"
    assert action in snapshot["caller_tools"], f"{action} missing from the pinned CALLER_TOOLS"
    rows = json.loads((OPENAPI / "miworkbench.index.json").read_text())["routes"]
    assert any((r["method"], r["path"]) == (method, path) for r in rows), "missing from the index"
    assert (method, path) not in {(r.method, r.path) for r in ROUTES.for_app("miworkbench")}
