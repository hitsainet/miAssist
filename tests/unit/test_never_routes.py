"""What miAssist never calls (A14; 001 FR-27, FTASKS 4.8)."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

from miassist.adapters.base import GateClass, ProgrammingError, Route
from miassist.adapters.routes import NEVER_ROUTES, ROUTES, RouteRegistry

OPENAPI = Path(__file__).resolve().parents[1] / "fixtures" / "openapi"
APPS = ("miworkbench", "miserver", "midataworks", "miforge")


def index(app: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = json.loads((OPENAPI / f"{app}.index.json").read_text())["routes"]
    return rows


@pytest.mark.parametrize("never", NEVER_ROUTES, ids=lambda n: n.id)
def test_patterns_match_index(never: Any) -> None:
    hits = [
        (app, r["method"], r["path"])
        for app in APPS
        for r in index(app)
        if never.matches(app, r["method"], r["path"])
    ]
    assert hits, f"{never.id} matches nothing in any app's route index: a renamed route slips past"


def test_none_registered() -> None:
    for route in ROUTES:
        for never in NEVER_ROUTES:
            assert not never.matches(route.app, route.method, route.path), (route.id, never.id)


@pytest.mark.parametrize(
    ("app", "method", "path", "never_id"),
    [
        ("miserver", "POST", "/api/probes/{probe_id}/arm", "miserver.probe_arm"),
        ("miserver", "POST", "/api/probes/behaviours/{key}/arm", "miserver.behaviour_arm"),
        ("miserver", "POST", "/api/clusters/{cluster_id}/activate", "miserver.cluster_activation"),
        ("miserver", "PUT", "/api/clusters/{cluster_id}/intensity", "miserver.cluster_activation"),
        (
            "miserver",
            "POST",
            "/api/circuits/{circuit_id}/deactivate",
            "miserver.circuit_activation",
        ),
        ("miserver", "POST", "/api/clusters/hub/import", "miserver.hub"),
        ("midataworks", "POST", "/api/v1/generation-runs", "midataworks.generation_start"),
        ("miserver", "PUT", "/api/settings/hf-token", "any.token_write"),
        (
            "miworkbench",
            "POST",
            "/api/v1/mcp/approvals/{request_id}/consume",
            "miworkbench.consume",
        ),
        ("miforge", "POST", "/api/v1/wsp/endpoints", "miforge.wsp_endpoint_register"),
        (
            "miforge",
            "PATCH",
            "/api/v1/wsp/endpoints/{endpoint_id}",
            "miforge.wsp_endpoint_change",
        ),
        (
            "miforge",
            "DELETE",
            "/api/v1/wsp/endpoints/{endpoint_id}",
            "miforge.wsp_endpoint_remove",
        ),
    ],
)
def test_registration_refused(app: str, method: str, path: str, never_id: str) -> None:
    """Refused BY NAME: the fixture id carries no word the refusal could echo (R1 review fix
    OR1-001-1: the old id ``<app>.never_fixture`` let an unrelated refusal match "never")."""
    route = Route(f"{app}.fixture", app, method, path, GateClass.APP_GATED, "fixture")
    with pytest.raises(ProgrammingError, match=rf"never-route \({re.escape(never_id)}\)"):
        RouteRegistry((route,))


#: Every miServer Hub row in the committed route index (R1 review fix OR1-001-1, 2026-11-16).
HUB = [(r["method"], r["path"]) for r in index("miserver") if "/hub" in r["path"]]


def test_hub_rows_exist() -> None:
    """Both families (probes and clusters) and both verbs: a narrowing cannot hide behind one row."""
    assert {p.split("/")[2] for _, p in HUB} == {"probes", "clusters"}
    assert len(HUB) >= 6


@pytest.mark.parametrize(("method", "path"), HUB)
def test_hub_route_refused_by_never_route(method: str, path: str) -> None:
    gate = GateClass.READ if method == "GET" else GateClass.APP_GATED
    route = Route("miserver.fixture", "miserver", method, path, gate, "fixture")
    with pytest.raises(ProgrammingError, match=r"never-route \(miserver\.hub\)"):
        RouteRegistry((route,))
