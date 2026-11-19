"""miServer's conditional gates and miForge's marked routes are never registered (A19, R2M-10,
R2M-12; 001 FTASKS 4.4: test_miserver_conditional, test_miforge_marked_routes)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from miassist.adapters.base import GateClass, Route
from miassist.adapters.routes import (
    MISERVER_CONDITIONAL_GATES,
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
    for method, path in marked:
        with pytest.raises(UnknownGate):
            classify_marker("miforge", method, path, {"x-approval-action": "x"})
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
    assert "x-approval-when" not in row, "miForge now states its condition: reclassify (A19)"
    assert (method, path) not in {(r.method, r.path) for r in ROUTES.for_app("miforge")}
