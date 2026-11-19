"""The Hub check (A17, A23; 001 FTASKS 4.11; NC-A23-1..5)."""

from __future__ import annotations

from typing import Any

import pytest

from miassist.adapters.base import Handoff, PublicCheck, Resource, issue_public_check
from miassist.hub.public_check import public_hub_search, run_public_check
from tests.support.clients import client_for, no_pending, test_registry
from tests.support.fake_apps import FakeApp, Recorded

REPO = "evalfx-org/data"


def dataworks(items: list[dict[str, Any]]) -> FakeApp:
    fake = no_pending(FakeApp("midataworks"))
    fake.on("POST", "/api/v1/sources/hf/search", {"items": items})
    fake.on(
        "POST",
        "/api/v1/sources/hf/preview",
        {"splits": [{"bytes": 10}, {"bytes": 5}], "licence": "mit"},
    )
    fake.on("POST", "/api/v1/sources/hf", {"source_id": "s1"})
    return fake


def item(repo: str, private: bool = False, gated: bool = False) -> dict[str, Any]:
    return {"repo_id": repo, "private": private, "gated": gated, "licence": "mit"}


async def test_preview_after_check() -> None:
    fake = dataworks([item(REPO)])
    clients = {"midataworks": client_for(fake)}
    check = await run_public_check(clients, REPO, with_size=True)
    assert isinstance(check, PublicCheck) and check.public and check.bytes == 15
    order = [r.template for r in fake.requests if r.method == "POST"]
    assert order == ["/api/v1/sources/hf/search", "/api/v1/sources/hf/preview"]
    assert fake.calls("POST", "/api/v1/sources/hf/search")[0].body["query"] == REPO


@pytest.mark.parametrize(
    ("label", "items"),
    [
        ("private", [item(REPO, private=True)]),
        ("gated", [item(REPO, gated=True)]),
        ("case-differs", [item(REPO.upper())]),
        ("absent", [item("evalfx-org/other")]),
    ],
)
async def test_not_public_never_previews(label: str, items: list[dict[str, Any]]) -> None:
    fake = dataworks(items)
    check = await run_public_check({"midataworks": client_for(fake)}, REPO, with_size=True)
    assert isinstance(check, PublicCheck) and check.public is False
    assert fake.calls("POST", "/api/v1/sources/hf/preview") == []


@pytest.mark.parametrize("given", ["none", "not-public", "other-repo"])
async def test_refused_without_passing_check(given: str) -> None:
    fake = dataworks([item(REPO)])
    registry = test_registry()
    client = client_for(fake, registry=registry)
    checks: dict[str, PublicCheck | None] = {
        "none": None,
        "not-public": issue_public_check(REPO, False, None, None),
        "other-repo": issue_public_check("evalfx-org/other", True, 1, None),
    }
    answer = await client.call(
        registry.get("midataworks.fixture_import"),
        json={"repo_id": REPO},
        public_check=checks[given],
    )
    assert isinstance(answer, Handoff)
    assert fake.calls("POST", "/api/v1/sources/hf") == []


async def test_passing_check_sends_once() -> None:
    fake = dataworks([item(REPO)])
    registry = test_registry()
    client = client_for(fake, registry=registry)
    check = issue_public_check(REPO, True, 15, "mit")
    answer = await client.call(
        registry.get("midataworks.fixture_import"), json={"repo_id": REPO}, public_check=check
    )
    assert isinstance(answer, Resource)
    assert len(fake.calls("POST", "/api/v1/sources/hf")) == 1


async def test_no_midataworks_handoff() -> None:
    assert isinstance(await run_public_check({}, REPO, with_size=False), Handoff)


def test_touches_hub_coverage() -> None:
    registry = test_registry()
    for route_id in ("midataworks.fixture_import", "midataworks.hf_preview"):
        route = registry.get(route_id)
        assert route.touches_hub and route.hub_repo_param == "body.repo_id"
    assert not registry.get("midataworks.hf_search").touches_hub, "the search IS the check"


async def test_public_hub_search_drops_private_and_gated() -> None:
    fake = dataworks(
        [item("a/public"), item("b/private", private=True), item("c/gated", gated=True)]
    )
    result = await public_hub_search({"midataworks": client_for(fake)}, "q", 5, ["mit"])
    assert not isinstance(result, Handoff | Resource)
    kept, dropped = result
    assert [c.repo_id for c in kept] == ["a/public"]
    assert dropped == 2


def test_public_check_cannot_be_fabricated() -> None:
    from miassist.adapters.base import ProgrammingError

    with pytest.raises(ProgrammingError):
        PublicCheck(REPO, True, 1, None, object())  # type: ignore[call-arg]


def _unused(_: Recorded) -> None:
    return None
