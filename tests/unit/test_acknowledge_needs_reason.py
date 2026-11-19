"""``acknowledge_*`` needs the person's own reason, on the body and on a filing's nested canonical
payload (FR-27, R3M-5; 001 FTASKS 4.8; NC-R3M-5)."""

from __future__ import annotations

import pytest

from miassist.adapters.base import Resource
from miassist.errors import MiAssistError
from tests.support.clients import client_for, no_pending, test_registry
from tests.support.fake_apps import FakeApp


@pytest.mark.parametrize("key", ["acknowledge_unvalidated", "acknowledge_below_rung2"])
async def test_body_needs_reason(key: str) -> None:
    fake = no_pending(FakeApp("miforge")).on("POST", "/api/v1/fixture/runs", {"id": "r"})
    registry = test_registry()
    client = client_for(fake, registry=registry)
    route = registry.get("miforge.fixture_gated")
    with pytest.raises(MiAssistError) as caught:
        await client.call(route, json={key: True})
    assert caught.value.code == "needs_your_reason"
    with pytest.raises(MiAssistError):
        await client.call(route, json={key: True}, person_reason="   ")
    assert fake.calls("POST") == []
    answer = await client.call(route, json={key: True}, person_reason="I checked it by hand")
    assert isinstance(answer, Resource)


async def test_filing_payload_needs_reason() -> None:
    """NC-R3M-5's case: the acknowledgement is nested in the filing's canonical payload."""
    fake = no_pending(FakeApp("miworkbench")).on("POST", "/api/v1/mcp/approvals", {"id": "ap1"})
    registry = test_registry()
    client = client_for(fake, registry=registry)
    filing = {
        "tool_name": "build_probe_definition",
        "payload": {
            "_method": "POST",
            "_route": "/x",
            "body": {"acknowledge_below_rung2": {"why": "x"}},
        },
    }
    with pytest.raises(MiAssistError) as caught:
        await client.call(registry.get("miworkbench.file_approval"), json=filing)
    assert caught.value.code == "needs_your_reason"
    assert fake.calls("POST") == []


@pytest.mark.parametrize("value", ["true", "1", True])
async def test_query_needs_reason(value: object) -> None:
    """R1 review fix (OR1-001-9), 2026-11-16: miServer takes ``acknowledge_unvalidated`` as a QUERY
    parameter (circuit activation); the reason check covers the query too, before sending."""
    fake = no_pending(FakeApp("miforge")).on("POST", "/api/v1/fixture/runs", {"id": "r"})
    registry = test_registry()
    client = client_for(fake, registry=registry)
    route = registry.get("miforge.fixture_gated")
    with pytest.raises(MiAssistError) as caught:
        await client.call(route, params={"acknowledge_unvalidated": value})
    assert caught.value.code == "needs_your_reason"
    assert fake.calls("POST") == []
    answer = await client.call(
        route, params={"acknowledge_unvalidated": value}, person_reason="the operator asked"
    )
    assert isinstance(answer, Resource) and len(fake.calls("POST")) == 1
