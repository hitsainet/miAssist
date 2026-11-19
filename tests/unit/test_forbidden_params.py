"""Forbidden parameters are refused before sending (A20, R1M-3; 001 FTASKS 4.10; AC-14.6)."""

from __future__ import annotations

from types import MappingProxyType
from typing import Any

import pytest

from miassist.adapters.base import ANY, GateClass, ProgrammingError, Route, issue_public_check
from miassist.adapters.routes import REQUIRED_FORBIDDEN, RouteRegistry
from miassist.errors import MiAssistError
from tests.support.clients import client_for, no_pending, test_registry
from tests.support.fake_apps import FakeApp

CASES: dict[str, tuple[str, str, dict[str, Any]]] = {
    "query-activate": (
        "miserver",
        "miserver.fixture_import_cluster",
        {"params": {"activate": "true"}},
    ),
    'query-activate-"1"': (
        "miserver",
        "miserver.fixture_import_cluster",
        {"params": {"activate": "1"}},
    ),
    "body-access-token": (
        "midataworks",
        "midataworks.fixture_import",
        {"json": {"repo_id": "evalfx-org/data", "access_token": "x"}},
    ),
    'confirm-large-"true"': (
        "midataworks",
        "midataworks.fixture_import",
        {"json": {"repo_id": "evalfx-org/data", "confirm_large": "true"}},
    ),
    "publish-checks-repo-id": (
        "midataworks",
        "midataworks.fixture_publish_checks",
        {"path_params": {"version_id": "v1"}, "json": {"repo_id": "someone/else"}},
    ),
}


@pytest.mark.parametrize("case", sorted(CASES))
async def test_refused_before_sending(case: str) -> None:
    app, route_id, kwargs = CASES[case]
    fake = no_pending(FakeApp(app))
    registry = test_registry()
    route = registry.get(route_id)
    check = issue_public_check("evalfx-org/data", True, 10, "mit")
    extra: dict[str, Any] = {"public_check": check} if route.touches_hub else {}
    with pytest.raises(MiAssistError) as caught:
        await client_for(fake, registry=registry).call(route, **kwargs, **extra)
    assert caught.value.code == "forbidden_argument"
    assert fake.requests == [], "a refused call sent a request"


async def test_absent_is_sent_once() -> None:
    fake = FakeApp("miserver")
    registry = test_registry()
    route = registry.get("miserver.fixture_import_cluster")
    fake.on("POST", route.path, {"data": {"id": "c1"}})
    await client_for(fake, registry=registry).call(route, json={"definition": {}})
    assert len(fake.calls("POST", route.path)) == 1


@pytest.mark.parametrize(
    ("label", "key"),
    [
        ("clusters-import", ("miserver", "POST", "/api/clusters/import")),
        ("hub-import", ("miserver", "POST", "/api/clusters/hub/import")),
        ("publish-checks", ("midataworks", "POST", "/api/v1/versions/{version_id}/publish-checks")),
        ("wb-download", ("miworkbench", "POST", "/api/v1/datasets/download")),
        ("dw-import", ("midataworks", "POST", "/api/v1/sources/hf")),
        ("dw-preview", ("midataworks", "POST", "/api/v1/sources/hf/preview")),
    ],
)
def test_required_forbidden_at_registration(label: str, key: tuple[str, str, str]) -> None:
    app, method, path = key
    assert key in REQUIRED_FORBIDDEN
    bare = Route(
        f"{app}.bare_{label.replace('-', '_')}",
        app,
        method,
        path,
        GateClass.APP_GATED,
        "no forbidden declaration",
    )
    with pytest.raises(ProgrammingError):
        RouteRegistry((bare,))
    if label == "clusters-import":
        weak = Route(
            "miserver.weak_import",
            app,
            method,
            path,
            GateClass.APP_GATED,
            "forbids only activate=true",
            forbidden=MappingProxyType({"query.activate": True}),
        )
        with pytest.raises(ProgrammingError):
            RouteRegistry((weak,))


def test_required_entries() -> None:
    assert {k: dict(v) for k, v in REQUIRED_FORBIDDEN.items()} == {
        ("miserver", "POST", "/api/clusters/import"): {"query.activate": ANY},
        ("miserver", "POST", "/api/clusters/hub/import"): {"body.activate": ANY},
        ("midataworks", "POST", "/api/v1/versions/{version_id}/publish-checks"): {
            "body.repo_id": ANY
        },
        ("miworkbench", "POST", "/api/v1/datasets/download"): {"body.access_token": ANY},
        ("midataworks", "POST", "/api/v1/sources/hf"): {
            "body.access_token": ANY,
            "body.confirm_large": ANY,
        },
        ("midataworks", "POST", "/api/v1/sources/hf/preview"): {"body.access_token": ANY},
    }
