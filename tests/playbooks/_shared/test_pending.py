"""``_shared.pending`` per app, as 003's two callers use it (FTDD §6; FPRD FR-003.13, FR-003.19,
FR-003.20; FTASKS 4.1; A43, V-5).

Integration (OVN-miassist-int-13), 2026-11-16: ported to the ONE merged module (OR1-pb-10, the 004/005
fixer's contract): 003's gate calls ``open_id(..., include_closed=True)``, its send
``open_id(..., payload_digest=digest(body), keys=tuple(body))``; every app keeps the filed payload
under ``payload``. 004/005's own cases are in ``tests/unit/test_shared_pending.py``."""

from __future__ import annotations

from typing import Any

import pytest

from miassist.playbooks._shared import pending
from tests.support.clients import client_for
from tests.support.fake_apps import FakeApp

PAYLOAD = {"_method": "POST", "_route": "/r", "x": 1}


def rows(
    app: str, requested_by: str, status: str = "pending", payload: Any = PAYLOAD
) -> list[dict[str, Any]]:
    key = "tool_name" if app == "miworkbench" else "action"
    field = "payload"
    return [
        {
            "id": "ap-1",
            "approval_id": "ap-1",
            "status": status,
            key: "act",
            "requested_by": requested_by,
            field: payload,
        }
    ]


PATHS = {
    "miworkbench": "/api/v1/mcp/approvals",
    "midataworks": "/api/v1/approvals",
    "miserver": "/api/approvals",
}


async def gate_lookup(
    client: Any, action: str, payload_digest: str, remembered: str | None = None
) -> str | None:
    """003's gate (``detector_probe/actions.py``): open or closed outcomes of the same request."""
    return await pending.open_id(
        client,
        action,
        payload_digest=payload_digest,
        remembered=remembered,
        include_closed=True,
    )


async def send_lookup(
    client: Any, action: str, body: dict[str, Any], include_closed: bool = True
) -> str | None:
    """003's miDataworks send: the digest over the keys it sent (OR1-pb-10b); closed outcomes too
    unless the person asked again (Confirmation fix C-int-1, 2026-11-16)."""
    return await pending.open_id(
        client,
        action,
        payload_digest=pending.digest(body),
        keys=tuple(body),
        include_closed=include_closed,
    )


def fake(app: str, listed: list[dict[str, Any]]) -> FakeApp:
    f = FakeApp(app)
    f.on(
        "GET",
        PATHS[app],
        lambda r: (
            {"approvals": [x for x in listed if x["status"] == r.params.get("status")]}
            if app == "miworkbench"
            else {"items": [x for x in listed if x["status"] == r.params.get("status")]}
        ),
    )
    return f


@pytest.mark.parametrize("app", sorted(PATHS))
async def test_finds_its_own_row(app: str) -> None:
    f = fake(app, rows(app, pending.REQUESTED_BY[app]))
    found = await gate_lookup(client_for(f), "act", pending.digest(PAYLOAD))
    assert found == "ap-1"


@pytest.mark.parametrize("app", sorted(PATHS))
async def test_ignores_another_requester_action_or_payload(app: str) -> None:
    for listed, action, payload in (
        (rows(app, "someone-else"), "act", PAYLOAD),
        (rows(app, pending.REQUESTED_BY[app]), "other_act", PAYLOAD),
        (rows(app, pending.REQUESTED_BY[app]), "act", {**PAYLOAD, "x": 2}),
    ):
        f = fake(app, listed)
        assert await gate_lookup(client_for(f), action, pending.digest(payload)) is None


def test_requested_by_as_each_app_records_it() -> None:
    assert pending.REQUESTED_BY == {
        "miworkbench": "miassist",
        "midataworks": "agent:miassist",
        "miserver": "agent:miassist",
        "miforge": "agent:miassist",
    }


async def test_workbench_row_recorded_with_the_raw_header_value() -> None:
    """The miWorkbench row records ``miassist`` (no ``agent:``); a lookup for ``agent:miassist``
    would miss it and file again (R1M-14)."""
    f = fake("miworkbench", rows("miworkbench", "miassist"))
    found = await gate_lookup(client_for(f), "act", pending.digest(PAYLOAD))
    assert found == "ap-1"


async def test_a_denied_row_for_the_same_request_is_returned_not_refiled() -> None:
    f = fake("miworkbench", rows("miworkbench", "miassist", status="denied"))
    assert await gate_lookup(client_for(f), "act", pending.digest(PAYLOAD)) == "ap-1"


CLOSED_BY_APP = [
    (app, status)
    for app in sorted(PATHS)
    for status in (("denied",) if app == "miworkbench" else ("rejected",)) + ("expired", "failed")
]


@pytest.mark.parametrize(("app", "status"), CLOSED_BY_APP)
async def test_a_closed_row_is_found_only_with_include_closed(app: str, status: str) -> None:
    """Confirmation fix (C-int-1), 2026-11-16: each app's closed statuses are searched with
    ``include_closed`` (miDataworks and miServer say ``rejected``), so a closed request is reported
    instead of filed again; without it (the person asked again) only an open one is found."""
    f = fake(app, rows(app, pending.REQUESTED_BY[app], status=status))
    client = client_for(f)
    digest = pending.digest(PAYLOAD)
    assert await pending.open_id(client, "act", payload_digest=digest, include_closed=True) == (
        "ap-1"
    )
    assert await pending.open_id(client, "act", payload_digest=digest) is None


@pytest.mark.parametrize("status", ["rejected", "expired"])
async def test_a_remembered_closed_send_is_returned_only_with_include_closed(status: str) -> None:
    f = fake("midataworks", [])
    f.on(
        "GET",
        "/api/v1/approvals/{approval_id}",
        lambda r: {
            "id": r.path_params["approval_id"],
            "status": status,
            "action": "act",
            "requested_by": "agent:miassist",
        },
    )
    client = client_for(f)
    body = {"set_ids": ["evalfx-set-1"], "visibility": "private"}
    found = await pending.open_id(
        client,
        "act",
        payload_digest=pending.digest(body),
        keys=tuple(body),
        remembered="ap-old",
        include_closed=True,
    )
    assert found == "ap-old"
    assert await send_lookup(client, "act", body, include_closed=False) is None


def test_digest_is_of_the_canonical_json() -> None:
    assert pending.digest({"b": 1, "a": [1, 2]}) == pending.digest({"a": [1, 2], "b": 1})
    assert pending.digest({"a": 1}) != pending.digest({"a": 1, "_route": "/r"})


async def test_dataworks_row_keeps_the_body_one_level_deep() -> None:
    """R1 review fix (OR1-pb-10b), 2026-11-16. miDataworks stores the caller's body under
    ``payload.body``, defaults filled in, with server-made facts beside it
    (``core/agent_origin.py:342-361``): only the fields the caller sent are compared."""
    sent = {"set_ids": ["evalfx-set-1"], "visibility": "private"}
    stored = {
        "body": {**sent, "repositories": {}, "namespace": None},
        "send_group_id": "dsg_new",
        "sends": [{"set_id": "evalfx-set-1", "send_id": "dsn_new"}],
        "visibility": "private",
    }
    row = {**rows("midataworks", "agent:miassist")[0], "payload": stored}
    f = fake("midataworks", [row])
    client = client_for(f)
    assert await send_lookup(client, "act", sent) == "ap-1"
    other = {**sent, "visibility": "public"}
    assert await send_lookup(client, "act", other) is None
    assert (
        await pending.open_id(client, "act", payload_digest=pending.digest(sent)) is None
    ), "without keys the stored body's filled-in defaults never equal the body sent"


@pytest.mark.parametrize("status", ["consumed", "executed", "cancelled"])
async def test_a_remembered_id_that_was_used_is_not_returned(status: str) -> None:
    """R1 review fix (OR1-pb-18), 2026-11-16: a remembered approval that is neither open nor closed
    unused (``consumed``) leads nowhere; the caller files a new one."""
    f = fake("miworkbench", [])
    f.on(
        "GET",
        "/api/v1/mcp/approvals/{request_id}",
        lambda r: {"id": r.path_params["request_id"], "status": status},
    )
    found = await gate_lookup(client_for(f), "act", pending.digest(PAYLOAD), "ap-old")
    assert found is None


async def test_a_remembered_pending_id_is_returned() -> None:
    f = fake("miworkbench", [])
    f.on(
        "GET",
        "/api/v1/mcp/approvals/{request_id}",
        lambda r: {
            "id": r.path_params["request_id"],
            "status": "pending",
            "tool_name": "act",
            "requested_by": "miassist",
        },
    )
    found = await gate_lookup(client_for(f), "act", pending.digest(PAYLOAD), "ap-old")
    assert found == "ap-old"


SERVER_EXECUTED = {
    **{a: PATHS[a] for a in ("midataworks", "miserver")},
    "miforge": "/api/v1/approvals",
}


@pytest.mark.parametrize("app", sorted(SERVER_EXECUTED))
async def test_an_approved_request_the_app_is_running_is_found_not_refiled(app: str) -> None:
    """R2 review fix (OR2-int-1), 2026-11-16: miDataworks, miServer and miForge run an approved
    request themselves (``pending -> executing -> executed``). While it runs (``executing``) a
    repeat call must find it; ``executed`` is done, so a later need files anew."""
    f = FakeApp(app)
    listed = rows(app, pending.REQUESTED_BY[app], status="executing")
    f.on(
        "GET",
        SERVER_EXECUTED[app],
        lambda r: {"items": [x for x in listed if x["status"] == r.params.get("status")]},
    )
    client = client_for(f)
    assert await send_lookup(client, "act", PAYLOAD) == "ap-1"
    assert await pending.open_id(client, "act", fields={"x": 1}) == "ap-1"
    listed[0]["status"] = "executed"
    assert await pending.open_id(client, "act", fields={"x": 1}) is None


@pytest.mark.parametrize("app", sorted(SERVER_EXECUTED))
@pytest.mark.parametrize("status,found", [("executing", "ap-old"), ("executed", None)])
async def test_a_remembered_server_executed_id(app: str, status: str, found: str | None) -> None:
    """R2 review fix (OR2-int-1), 2026-11-16: a remembered id the app is running is returned (the
    caller waits on it); one the app finished is not (a later need files anew). The row is the
    caller's own (``requested_by`` and action match), so only its status decides."""
    f = FakeApp(app)
    f.on("GET", SERVER_EXECUTED[app], lambda r: {"items": []})
    row = {**rows(app, pending.REQUESTED_BY[app], status=status)[0], "id": "ap-old"}
    f.on("GET", SERVER_EXECUTED[app] + "/{approval_id}", lambda r: row)
    client = client_for(f)
    got = await pending.open_id(client, "act", fields={"x": 1}, remembered="ap-old")
    assert got == found
