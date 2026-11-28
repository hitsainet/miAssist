"""The base client: the agent header, the registry, fixed route headers (001 FTASKS 4.2, 4.9)."""

from __future__ import annotations

import pytest

from miassist.adapters.base import (
    APPROVAL_ID_HEADER,
    HEADERS,
    GateClass,
    ProgrammingError,
    Resource,
    Route,
)
from miassist.adapters.routes import ROUTES, RouteRegistry
from tests.support.clients import client_for, test_registry
from tests.support.fake_apps import FakeApp, all_fakes

EXPECTED = {
    "miworkbench": ("X-MiStudio-Agent", "miassist"),
    "miserver": ("X-miLLM-Agent", "agent:miassist"),
    "midataworks": ("X-Dataworks-Agent", "agent:miassist"),
    "miforge": ("X-Miforge-Agent", "agent:miassist"),
}
LIST_ROUTE = {
    "miworkbench": "miworkbench.list_models",
    "miserver": "miserver.list_models",
    "midataworks": "midataworks.list_datasets",
    "miforge": "miforge.list_runs",
}


def test_header_table_is_the_padrs() -> None:
    assert dict(HEADERS) == EXPECTED


@pytest.mark.parametrize("app", sorted(EXPECTED))
async def test_headers(app: str) -> None:
    fake = FakeApp(app)
    route = ROUTES.get(LIST_ROUTE[app])
    fake.on("GET", route.path, {"items": []})
    answer = await client_for(fake).call(route)
    assert isinstance(answer, Resource), answer
    (request,) = fake.requests
    name, value = EXPECTED[app]
    assert request.headers[name.lower()] == value
    others = {h.lower() for a, (h, _) in EXPECTED.items() if a != app}
    assert not others & set(request.headers), "another app's agent header was sent"
    assert APPROVAL_ID_HEADER.lower() not in request.headers


async def test_undeclared_route_raises() -> None:
    fake = FakeApp("miforge")
    stray = Route(
        "miforge.stray", "miforge", "GET", "/api/v1/stray", GateClass.READ, "not registered"
    )
    with pytest.raises(ProgrammingError):
        await client_for(fake).call(stray)
    look_alike = Route(
        "miforge.list_runs", "miforge", "GET", "/api/v1/runs", GateClass.READ, "copy"
    )
    with pytest.raises(ProgrammingError):
        await client_for(fake).call(look_alike)
    with pytest.raises(ProgrammingError):
        await client_for(FakeApp("miserver")).call(ROUTES.get("miforge.list_runs"))
    assert fake.requests == []


async def test_fixed_route_headers() -> None:
    fake = FakeApp("miserver")
    registry = test_registry()
    route = registry.get("miserver.fixture_test_chat")
    fake.on("POST", route.path, {"choices": []})
    answer = await client_for(fake, registry=registry).call(
        route, json={"messages": []}, floor_scope="cluster-1"
    )
    assert isinstance(answer, Resource)
    (request,) = fake.requests
    assert request.headers["x-millm-load-policy"] == "refuse"
    assert request.headers["x-millm-agent"] == "agent:miassist"


def test_route_header_may_not_name_the_agent_header() -> None:
    from types import MappingProxyType

    bad = Route(
        "miserver.bad",
        "miserver",
        "GET",
        "/api/models",
        GateClass.READ,
        "x",
        headers=MappingProxyType({"X-miLLM-Agent": "agent:someone-else"}),
    )
    with pytest.raises(ProgrammingError, match="agent header"):
        RouteRegistry((bad,))


async def test_call_unreachable_sends_nothing() -> None:
    from miassist.adapters.base import Unavailable
    from tests.support.clients import StubSnapshot

    fake = FakeApp("miforge")
    answer = await client_for(fake, snapshot=StubSnapshot(down={"miforge": "timeout"})).call(
        ROUTES.get("miforge.list_runs")
    )
    assert isinstance(answer, Unavailable) and answer.reason == "timeout"
    assert fake.requests == []


# -- 4.7: the overview's reads per app, exact method, path, query and count (FR-24, AC-24.1) ---

OVERVIEW_EXPECTED = {
    "miworkbench": [
        ("GET", "/api/v1/models", {"page": "1", "limit": "3"}),
        ("GET", "/api/v1/saes", {"skip": "0", "limit": "3"}),
        ("GET", "/api/v1/datasets", {"page": "1", "limit": "3"}),
        ("GET", "/api/v1/probe-monitors/probes", {}),
    ],
    "miserver": [
        ("GET", "/api/models", {}),
        ("GET", "/api/probes/status", {}),
        ("GET", "/api/clusters", {}),
    ],
    # overview fix (2026-11-27): the lists the app answers in name order are read at the route's
    # maximum page and put newest first by miAssist; miDataworks' versions are asked for newest
    "midataworks": [
        ("GET", "/api/v1/datasets", {"page": "1", "limit": "200"}),
        ("GET", "/api/v1/versions", {"page": "1", "limit": "3", "order": "recent"}),
    ],
    "miforge": [
        ("GET", "/api/v1/runs", {"limit": "3", "offset": "0"}),
        ("GET", "/api/v1/packs", {}),
        ("GET", "/api/v1/checkpoints", {"limit": "1000"}),
    ],
}


@pytest.mark.parametrize("app", sorted(OVERVIEW_EXPECTED))
async def test_overview_calls(app: str) -> None:
    from mcp import Client

    from tests.support.scenarios import seed
    from tests.support.servers import make_server

    fakes = seed(all_fakes())
    mcp, deps = make_server((app,), fakes)
    await deps.runtime.detector.probe_all()
    for fake in fakes.values():
        fake.requests.clear()
    async with Client(mcp) as session:
        result = await session.call_tool("miassist_overview", {"app": app})
    assert not result.is_error, result.content
    sent = [(r.method, r.path, r.params) for r in fakes[app].requests]
    assert sent == OVERVIEW_EXPECTED[app]
    assert all(f.requests == [] for name, f in fakes.items() if name != app)


# -- R1 review: two lines no test reached (OR1-001-8, W-11 and F-4), 2026-11-16 ---------------


async def test_redirects_are_not_followed() -> None:
    """W-11: a redirect would carry the agent header to a path outside the route registry."""
    import httpx

    fake = FakeApp("miforge").on(
        "GET", "/api/v1/packs", lambda r: httpx.Response(307, headers={"location": "/elsewhere"})
    )
    fake.on("GET", "/elsewhere", {"items": []})
    client = client_for(fake)
    await client.call(client.guards.registry.get("miforge.list_packs"))
    assert [r.path for r in fake.requests] == ["/api/v1/packs"]


async def test_call_time_floor_check_bites_with_a_lax_registry() -> None:
    """F-4: registration already refuses an off-floor ungated write; the call-time check is the
    backstop when a registry is built without that check."""
    from miassist.adapters.base import GateClass, ProgrammingError, Route
    from miassist.adapters.routes import RouteRegistry

    class LaxRegistry(RouteRegistry):
        def register(self, route: Route) -> Route:
            self._by_id[route.id] = route
            return route

    route = Route(
        "miforge.fixture_off_floor",
        "miforge",
        "POST",
        "/api/v1/fixture/x",
        GateClass.UNGATED_WRITE,
        "fixture",
        floor_entry="made.up",
    )
    fake = FakeApp("miforge").on("POST", "/api/v1/fixture/x", {"ok": True})
    client = client_for(fake, registry=LaxRegistry((route,)))
    with pytest.raises(ProgrammingError, match="outside the write floor"):
        await client.call(route, json={})
    assert fake.calls("POST") == []
