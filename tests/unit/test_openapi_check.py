"""The runtime route check (001 FTASKS 3.4; FR-15, AC-15.5): on first reachability miAssist reads
the running app's OpenAPI description once; a registered route it lacks answers
``app_route_missing`` without a request, ``/health`` lists it, and the tool list is unchanged."""

from __future__ import annotations

import time
from typing import Any

from mcp import Client

from miassist.adapters.routes import ROUTES
from miassist.installed.openapi_check import OPENAPI_PATHS, missing_from
from tests.support.app_factory import FakeDatabase, client
from tests.support.fake_apps import FakeApp, all_fakes
from tests.support.servers import make_server


def document(
    app: str, *, without: str | None = None, rename_params: bool = False
) -> dict[str, Any]:
    paths: dict[str, dict[str, Any]] = {}
    for route in ROUTES.for_app(app):
        if route.path == without:
            continue
        path = route.path.replace("{", "{x_") if rename_params else route.path
        paths.setdefault(path, {})[route.method.lower()] = {"responses": {}}
    return {"openapi": "3.1.0", "paths": paths}


def forge(doc: dict[str, Any] | None) -> dict[str, FakeApp]:
    fakes = all_fakes()
    fakes["miforge"].on("GET", "/api/v1/runs", {"runs": [], "total": 0})
    fakes["miforge"].on("GET", "/api/v1/packs", [])
    fakes["miforge"].on("GET", "/api/v1/checkpoints", {"items": []})
    if doc is not None:
        fakes["miforge"].on("GET", OPENAPI_PATHS["miforge"], doc)
    return fakes


async def test_missing_route_is_refused_without_a_request() -> None:
    fakes = forge(document("miforge", without="/api/v1/packs"))
    mcp, deps = make_server(("miforge",), fakes)
    await deps.runtime.detector.probe_all()
    assert deps.runtime.route_check.missing("miforge") == {"miforge.list_packs"}
    fakes["miforge"].requests.clear()
    async with Client(mcp) as mcp_client:
        result = await mcp_client.call_tool("miassist_overview", {"app": "miforge"})
    assert result.is_error
    assert result.content[0].text.startswith("app_route_missing:")
    sent = [(r.method, r.path) for r in fakes["miforge"].requests]
    assert ("GET", "/api/v1/packs") not in sent
    assert sent == [("GET", "/api/v1/runs")]


async def test_tool_list_unchanged() -> None:
    names = []
    for doc in (document("miforge"), document("miforge", without="/api/v1/packs")):
        mcp, deps = make_server(("miforge",), forge(doc))
        await deps.runtime.detector.probe_all()
        async with Client(mcp) as mcp_client:
            names.append([t.name for t in (await mcp_client.list_tools()).tools])
    assert names[0] == names[1]


async def test_read_once_and_parameter_names_ignored() -> None:
    fakes = forge(document("miforge", rename_params=True))
    _, deps = make_server(("miforge",), fakes)
    for _ in range(3):
        await deps.runtime.detector.probe_all()
    assert deps.runtime.route_check.reads == {"miforge": 1}
    assert deps.runtime.route_check.missing("miforge") == frozenset()
    assert len(fakes["miforge"].calls("GET", OPENAPI_PATHS["miforge"])) == 1


async def test_unreadable_description_marks_nothing_and_retries() -> None:
    fakes = forge(None)
    _, deps = make_server(("miforge",), fakes)
    await deps.runtime.detector.probe_all()
    await deps.runtime.detector.probe_all()
    assert not deps.runtime.route_check.checked("miforge")
    assert deps.runtime.route_check.missing("miforge") == frozenset()
    assert deps.runtime.route_check.reads == {"miforge": 2}


def test_not_an_openapi_document() -> None:
    assert missing_from(ROUTES.for_app("miforge"), {"detail": "x"}) is None
    assert missing_from(ROUTES.for_app("miforge"), ["x"]) is None


def test_health_lists_missing_routes() -> None:
    fakes = forge(document("miforge", without="/api/v1/packs"))
    with client(
        FakeDatabase(),
        transports={a: f.transport() for a, f in fakes.items()},
        apps="miforge",
        miforge_url="http://miforge.test",
    ) as test_client:
        deadline = time.monotonic() + 2
        body: dict[str, Any] = {}
        while time.monotonic() < deadline:
            body = test_client.get("/health").json()
            if "missing_routes" in body:
                break
            time.sleep(0.02)
    assert body["missing_routes"] == {"miforge": ["miforge.list_packs"]}
