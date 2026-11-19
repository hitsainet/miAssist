"""Server-executed style: one call, never an approval id (A18; 001 FTASKS 5.5, 5.7)."""

from __future__ import annotations

import httpx
import pytest

from miassist.adapters.base import (
    APPROVAL_ID_HEADER,
    Pending,
    ProgrammingError,
    Resource,
    issue_approved_id,
)
from tests.support.clients import client_for, test_registry
from tests.support.fake_apps import FakeApp

SERVER_EXECUTED = {
    "miforge": ("miforge.fixture_gated", "/api/v1/fixture/runs", {}),
    "midataworks": ("midataworks.fixture_build_version", "/api/v1/versions", {}),
}


@pytest.mark.parametrize("app", sorted(SERVER_EXECUTED))
async def test_single_request(app: str) -> None:
    route_id, path, _ = SERVER_EXECUTED[app]
    fake = FakeApp(app).on("GET", "/api/v1/approvals", {"approvals": []})
    fake.on(
        "POST",
        path,
        lambda r: httpx.Response(202, json={"approval_id": "ap9", "status": "pending"}),
    )
    registry = test_registry()
    answer = await client_for(fake, registry=registry).call(registry.get(route_id), json={})
    assert isinstance(answer, Pending)
    assert answer.approval["then"] == "server_runs"
    assert len(fake.calls("POST")) == 1


@pytest.mark.parametrize("app", sorted(SERVER_EXECUTED))
async def test_no_id_to_server_executed(app: str) -> None:
    route_id, path, _ = SERVER_EXECUTED[app]
    fake = FakeApp(app).on("GET", "/api/v1/approvals", {"approvals": []})
    fake.on("POST", path, {"ok": True})
    registry = test_registry()
    client = client_for(fake, registry=registry)
    with pytest.raises(ProgrammingError):
        await client.call(
            registry.get(route_id),
            json={},
            approval_id=issue_approved_id("a", {"status": "approved"}),
        )
    await client.call(registry.get(route_id), json={})
    for request in fake.requests:
        assert APPROVAL_ID_HEADER.lower() not in request.headers


async def test_202_on_write_is_wait() -> None:
    fake = FakeApp("midataworks").on("GET", "/api/v1/approvals", {"approvals": []})
    fake.on(
        "POST",
        "/api/v1/versions",
        lambda r: httpx.Response(
            202, json={"approval_id": "ap1", "status": "pending", "action": "agent_label_rows"}
        ),
    )
    registry = test_registry()
    answer = await client_for(fake, registry=registry).call(
        registry.get("midataworks.fixture_build_version"), json={"dataset_id": "d"}
    )
    assert isinstance(answer, Pending)
    assert answer.approval["then"] == "server_runs"
    assert len(fake.calls("POST")) == 1


@pytest.mark.parametrize("accepted", ["BuildAccepted", "ImportAccepted"])
async def test_202_accepted_job_is_data(accepted: str) -> None:
    fake = FakeApp("midataworks").on("GET", "/api/v1/approvals", {"approvals": []})
    fake.on(
        "POST",
        "/api/v1/versions",
        lambda r: httpx.Response(202, json={"job_id": "j1", "kind": accepted}),
    )
    registry = test_registry()
    answer = await client_for(fake, registry=registry).call(
        registry.get("midataworks.fixture_build_version"), json={"dataset_id": "d"}
    )
    assert isinstance(answer, Resource)
    assert answer.body == {"job_id": "j1", "kind": accepted}
