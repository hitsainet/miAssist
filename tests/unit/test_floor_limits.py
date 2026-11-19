"""The floor is bounded (A24, A37; 001 FTASKS 4.12)."""

from __future__ import annotations

import pytest

from miassist.adapters.base import GateClass, ProgrammingError, Resource
from miassist.adapters.limits import FLOOR_LIMITS, FloorLimiter, Limit, limits_with_overrides
from miassist.adapters.routes import ROUTES, UNGATED_WRITES_ALLOWED
from miassist.errors import MiAssistError
from tests.support.clients import client_for, no_pending, test_registry
from tests.support.fake_apps import FakeApp


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


async def test_test_chat_once_per_cluster_per_hour() -> None:
    fake = FakeApp("miserver")
    registry = test_registry()
    route = registry.get("miserver.fixture_test_chat")
    fake.on("POST", route.path, {"choices": []})
    clock = Clock()
    client = client_for(fake, registry=registry, limiter=FloorLimiter(clock=clock))
    await client.call(route, json={"messages": []}, floor_scope="cluster-a")
    with pytest.raises(MiAssistError) as caught:
        await client.call(route, json={"messages": []}, floor_scope="cluster-a")
    assert caught.value.code == "floor_limit"
    assert len(fake.calls("POST", route.path)) == 1
    await client.call(route, json={"messages": []}, floor_scope="cluster-b")
    assert len(fake.calls("POST", route.path)) == 2
    clock.now += 3600
    await client.call(route, json={"messages": []}, floor_scope="cluster-a")
    assert len(fake.calls("POST", route.path)) == 3


async def test_scoped_entry_needs_a_scope() -> None:
    with pytest.raises(ProgrammingError):
        await FloorLimiter().take("steering.test_chat", None)


def test_every_entry_limited() -> None:
    assert set(UNGATED_WRITES_ALLOWED) <= set(FLOOR_LIMITS)
    budgets = {r.budget or r.floor_entry for r in ROUTES if r.gate is GateClass.UNGATED_WRITE}
    assert budgets and budgets <= set(FLOOR_LIMITS)
    assert FLOOR_LIMITS["steering.test_chat"] == Limit(1, 3600, scoped=True)
    assert FLOOR_LIMITS["hub.search"] == Limit(20, 3600)
    assert FLOOR_LIMITS["hub.preview"] == Limit(20, 3600)
    assert FLOOR_LIMITS["import.hf_midataworks"] == Limit(5, 3600)


async def test_search_budget() -> None:
    fake = FakeApp("midataworks")
    route = ROUTES.get("midataworks.hf_search")
    fake.on("POST", route.path, {"items": []})
    client = client_for(fake, registry=test_registry())
    route = client.guards.registry.get("midataworks.hf_search")
    for _ in range(20):
        assert isinstance(await client.call(route, json={"query": "x", "limit": 5}), Resource)
    with pytest.raises(MiAssistError) as caught:
        await client.call(route, json={"query": "x", "limit": 5})
    assert caught.value.code == "floor_limit"
    assert len(fake.calls("POST", route.path)) == 20


async def test_preview_spares_import_budget() -> None:
    limiter = FloorLimiter()
    for _ in range(20):
        await limiter.take("hub.preview", None)
    for _ in range(5):
        await limiter.take("import.hf_midataworks", None)
    with pytest.raises(MiAssistError):
        await limiter.take("import.hf_midataworks", None)


async def test_refused_call_consumes_no_slot() -> None:
    """A call refused by the pending cap (or any earlier refusal) takes no rate slot (A37)."""
    fake = FakeApp("midataworks")
    registry = test_registry()
    route = registry.get("midataworks.fixture_build_version")
    pending = [
        {"id": str(i), "status": "pending", "requested_by": "agent:miassist"} for i in range(10)
    ]
    fake.on("GET", "/api/v1/approvals", {"approvals": pending})
    limiter = FloorLimiter()
    client = client_for(fake, registry=registry, limiter=limiter)
    with pytest.raises(MiAssistError) as caught:
        await client.call(route, json={"dataset_id": "d"})
    assert caught.value.code == "too_many_pending"
    assert not any(limiter._uses.values()), "a refused call consumed a rate slot"


def test_overrides_change_but_never_remove() -> None:
    limits = limits_with_overrides('{"hub.search": {"count": 3}}')
    assert limits["hub.search"] == Limit(3, 3600)
    assert set(limits) == set(FLOOR_LIMITS)
    with pytest.raises(SystemExit):
        limits_with_overrides('{"no.such": {"count": 1}}')


async def test_preview_without_check_is_a_handoff() -> None:
    from miassist.adapters.base import Handoff

    fake = no_pending(FakeApp("midataworks"))
    client = client_for(fake)
    route = client.guards.registry.get("midataworks.hf_preview")
    answer = await client.call(route, json={"repo_id": "evalfx-org/data"})
    assert isinstance(answer, Handoff)
    assert fake.calls("POST", route.path) == []
