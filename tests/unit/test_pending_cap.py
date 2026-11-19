"""The pending-approval cap (A24, R3M-16, R3M-17; 001 FTASKS 4.12)."""

from __future__ import annotations

from typing import Any

import pytest

from miassist.adapters.base import Resource, issue_approved_id
from miassist.errors import MiAssistError
from tests.support.clients import client_for, test_registry
from tests.support.fake_apps import FakeApp, Recorded

GATED = {
    "miforge": ("miforge.fixture_gated", "/api/v1/approvals", "agent:miassist"),
    "midataworks": ("midataworks.fixture_build_version", "/api/v1/approvals", "agent:miassist"),
}


def items(n: int, by: str, start: int = 0) -> list[dict[str, Any]]:
    return [{"id": f"a{start + i}", "status": "pending", "requested_by": by} for i in range(n)]


@pytest.mark.parametrize("app", sorted(GATED))
async def test_cap(app: str) -> None:
    route_id, list_path, me = GATED[app]
    fake = FakeApp(app).on("GET", list_path, {"approvals": items(10, me)})
    registry = test_registry()
    route = registry.get(route_id)
    with pytest.raises(MiAssistError) as caught:
        await client_for(fake, registry=registry).call(route, json={})
    assert caught.value.code == "too_many_pending"
    assert fake.calls("POST") == [], "a capped call reached the route"


async def test_others_do_not_count() -> None:
    fake = FakeApp("miforge").on(
        "GET", "/api/v1/approvals", {"approvals": items(10, "agent:other")}
    )
    fake.on("POST", "/api/v1/fixture/runs", {"id": "r"})
    registry = test_registry()
    await client_for(fake, registry=registry).call(registry.get("miforge.fixture_gated"), json={})
    assert len(fake.calls("POST")) == 1


async def test_cap_miworkbench_sixty_others() -> None:
    """Sixty newer pending rows from others come ahead of miAssist's ten: the read pages."""
    rows = items(60, "other-agent") + items(10, "miassist", start=100)

    def page(request: Recorded) -> dict[str, Any]:
        limit = int(request.params.get("limit", 50))
        offset = int(request.params.get("offset", 0))
        return {"approvals": rows[offset : offset + limit], "total": len(rows)}

    fake = FakeApp("miworkbench").on("GET", "/api/v1/mcp/approvals", page)
    registry = test_registry()
    with pytest.raises(MiAssistError) as caught:
        await client_for(fake, registry=registry).call(
            registry.get("miworkbench.file_approval"), json={"tool_name": "x", "payload": {}}
        )
    assert caught.value.code == "too_many_pending"
    (read,) = fake.calls("GET", "/api/v1/mcp/approvals")
    assert read.params["limit"] == "500" and read.params["status"] == "pending"


async def test_cap_pages_beyond_one_page() -> None:
    rows = items(500, "other-agent") + items(10, "miassist", start=1000)

    def page(request: Recorded) -> dict[str, Any]:
        offset = int(request.params.get("offset", 0))
        return {"approvals": rows[offset : offset + 500], "total": len(rows)}

    fake = FakeApp("miworkbench").on("GET", "/api/v1/mcp/approvals", page)
    registry = test_registry()
    with pytest.raises(MiAssistError):
        await client_for(fake, registry=registry).call(
            registry.get("miworkbench.file_approval"), json={"tool_name": "x", "payload": {}}
        )
    assert len(fake.calls("GET", "/api/v1/mcp/approvals")) == 2


async def test_cap_approved_call_not_capped() -> None:
    fake = FakeApp("miworkbench").on(
        "GET", "/api/v1/mcp/approvals", {"approvals": items(10, "miassist")}
    )
    fake.on("POST", "/api/v1/fixture/probe-runs/{probe_id}/start", {"task_id": "t"})
    registry = test_registry()
    route = registry.get("miworkbench.fixture_start_gpu_job")
    approved = issue_approved_id("a1", {"status": "approved"})
    answer = await client_for(fake, registry=registry).call(
        route, path_params={"probe_id": "p"}, json={}, approval_id=approved
    )
    assert isinstance(answer, Resource)
    assert fake.calls("GET", "/api/v1/mcp/approvals") == []


# -- R2 review fix (OR2-001-3), 2026-11-16: the reviewer's tests, extended ------------------------
# The cap's two fail-closed paths (OVN-miassist-core-11: never file uncounted) and each app's own
# identity, for every app. Each app's list path and requested_by value are written here, not read
# from the code (ADR-006's table).

LIST = {
    "miworkbench": "/api/v1/mcp/approvals",
    "miserver": "/api/approvals",
    "midataworks": "/api/v1/approvals",
    "miforge": "/api/v1/approvals",
}
ME = {
    "miworkbench": "miassist",
    "miserver": "agent:miassist",
    "midataworks": "agent:miassist",
    "miforge": "agent:miassist",
}


async def check_cap(app: str, answer: Any) -> FakeApp:
    from miassist.adapters.limits import PendingCap

    fake = FakeApp(app).on("GET", LIST[app], answer)
    await PendingCap(cap=10).check(app, client_for(fake, registry=test_registry()))
    return fake


@pytest.mark.parametrize("app", sorted(LIST))
async def test_cap_counts_this_apps_identity(app: str) -> None:
    from miassist.adapters.limits import REQUESTED_BY

    with pytest.raises(MiAssistError) as caught:
        await check_cap(app, {"approvals": items(10, ME[app])})
    assert caught.value.code == "too_many_pending"
    assert REQUESTED_BY[app] == ME[app]
    # The control: nine of them pass.
    await check_cap(app, {"approvals": items(9, ME[app])})


@pytest.mark.parametrize("status", [500, 503, 404, 422])
@pytest.mark.parametrize("app", sorted(LIST))
async def test_unreadable_answer_files_nothing(app: str, status: int) -> None:
    """An app error (4xx/5xx) or an unavailable app (502-504): ``pending_cap_unreadable``."""
    import httpx

    with pytest.raises(MiAssistError) as caught:
        await check_cap(app, lambda _r: httpx.Response(status, json={"error": {"code": "boom"}}))
    assert caught.value.code == "pending_cap_unreadable"
    assert "files nothing" in caught.value.message


@pytest.mark.parametrize("body", [{"something_else": 3}, {"approvals": "x"}, [1, 2], None], ids=str)
@pytest.mark.parametrize("app", sorted(LIST))
async def test_unknown_shape_files_nothing(app: str, body: Any) -> None:
    with pytest.raises(MiAssistError) as caught:
        await check_cap(app, body)
    assert caught.value.code == "pending_cap_unreadable"


async def test_unreadable_list_refuses_the_gated_call_before_it_is_sent() -> None:
    """Wiring: through ``call`` on a gated route, an unreadable list refuses and the route is
    never reached (the payload never leaves)."""
    import httpx

    route_id, list_path, _ = GATED["miforge"]
    fake = FakeApp("miforge").on("GET", list_path, lambda _r: httpx.Response(500, json={}))
    registry = test_registry()
    with pytest.raises(MiAssistError) as caught:
        await client_for(fake, registry=registry).call(registry.get(route_id), json={})
    assert caught.value.code == "pending_cap_unreadable"
    assert fake.calls("POST") == []
    assert len(fake.calls("GET")) == 1
