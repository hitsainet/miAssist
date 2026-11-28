"""The ONE repeat-call lookup shared by 003, 004 and 005 (R1 review fix OR1-pb-10, OR1-pb-18,
2026-11-16). Rows are built from each app's response shapes (``tests/support/shapes.py``)."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest

from miassist.playbooks._shared import pending
from tests.support import shapes
from tests.support.fake_apps import FakeApp
from tests.support.servers import make_deps, mark_reachable
from tests.support.shapes import instance, shaped_fakes

APPS = ("miworkbench", "midataworks", "miserver")


@pytest.fixture(autouse=True)
def answers_are_the_apps() -> Iterator[None]:
    shapes.collected()
    yield
    found = shapes.collected()
    assert not found, "\n".join(found[:20])


WB_PAYLOAD = {"_method": "POST", "_route": "/api/v1/steering/async/sweep", "prompt": "hi"}


def wb_row(id_: str, status: str, payload: dict[str, Any], by: str = "miassist") -> Any:
    return instance(
        "miworkbench",
        "GET /api/v1/mcp/approvals/{request_id}",
        200,
        id=id_,
        status=status,
        tool_name="steer_sweep",
        payload=payload,
        requested_by=by,
        created_at=f"2026-11-16T00:00:{id_[-1]}0Z",
    )


def dw_row(id_: str, status: str, payload: dict[str, Any]) -> Any:
    return instance(
        "midataworks",
        "GET /api/v1/approvals/{approval_id}",
        200,
        id=id_,
        status=status,
        action="hub_push",
        payload=payload,
        requested_by="agent:miassist",
    )


def sv_row(id_: str, status: str, payload: dict[str, Any]) -> dict[str, Any]:
    """miServer's ``approval_service.as_payload`` (``approval_id``, not ``id``)."""
    return {
        "approval_id": id_,
        "action": "model_load",
        "action_label": "Load a model",
        "settings_change": False,
        "batch_kind": None,
        "status": status,
        "summary": {},
        "payload": payload,
        "request_digest": "sha256:x",
        "requested_by": "agent:miassist",
        "decided_by": None,
        "reason": None,
        "result": None,
        "error": None,
        "created_at": "2026-11-16T00:00:00+00:00",
        "decided_at": None,
        "expires_at": "2026-11-17T00:00:00+00:00",
        "batch_id": None,
    }


async def clients(rows: dict[str, list[dict[str, Any]]]) -> tuple[Any, dict[str, FakeApp]]:
    fakes = shaped_fakes(("miworkbench", "midataworks"))

    def lister(app: str, key: str) -> Any:
        def answer(r: Any) -> Any:
            found = [x for x in rows[app] if x["status"] == r.params.get("status", x["status"])]
            if app == "miworkbench":
                return instance(app, key, 200, approvals=found, total=len(found))
            if app == "midataworks":
                return instance(app, key, 200, approvals=found, total=len(found))
            return {"success": True, "data": {"approvals": found, "count": len(found)}}

        return answer

    def getter(app: str, param: str) -> Any:
        def answer(r: Any) -> Any:
            for x in rows[app]:
                if pending.row_id(x) == r.path_params[param]:
                    return {"success": True, "data": x} if app == "miserver" else x
            return fakes[app].error(404, "not_found")

        return answer

    fakes["miworkbench"].on(
        "GET", "/api/v1/mcp/approvals", lister("miworkbench", "GET /api/v1/mcp/approvals")
    )
    fakes["miworkbench"].on(
        "GET", "/api/v1/mcp/approvals/{request_id}", getter("miworkbench", "request_id")
    )
    fakes["midataworks"].on(
        "GET", "/api/v1/approvals", lister("midataworks", "GET /api/v1/approvals")
    )
    fakes["midataworks"].on(
        "GET", "/api/v1/approvals/{approval_id}", getter("midataworks", "approval_id")
    )
    fakes["miserver"].on("GET", "/api/approvals", lister("miserver", ""))
    fakes["miserver"].on("GET", "/api/approvals/{approval_id}", getter("miserver", "approval_id"))
    deps = make_deps(APPS, fakes)
    await mark_reachable(deps)
    return deps.runtime.clients, fakes


async def test_an_approved_unused_workbench_request_is_found_and_nothing_new_is_filed() -> None:
    """OR1-pb-10a: 005's repeat ``try`` after approval must find the approved request."""
    c, _ = await clients({"miworkbench": [wb_row("req-1", "approved", WB_PAYLOAD)]})
    found = await pending.open_request(
        c["miworkbench"], "steer_sweep", payload_digest=pending.digest(WB_PAYLOAD)
    )
    assert found is not None and found["id"] == "req-1"


async def test_consumed_or_foreign_requests_are_never_returned() -> None:
    """OR1-pb-18: a remembered id that was used, or that is not miAssist's, files anew."""
    rows = {
        "miworkbench": [
            wb_row("req-1", "consumed", WB_PAYLOAD),
            wb_row("req-2", "approved", WB_PAYLOAD, by="someone"),
        ]
    }
    c, _ = await clients(rows)
    digest = pending.digest(WB_PAYLOAD)
    for remembered in ("req-1", "req-2"):
        assert (
            await pending.open_id(
                c["miworkbench"],
                "steer_sweep",
                payload_digest=digest,
                remembered=remembered,
                include_closed=True,
            )
            is None
        )


async def test_a_remembered_closed_request_is_returned_only_when_asked() -> None:
    c, _ = await clients({"miworkbench": [wb_row("req-1", "denied", WB_PAYLOAD)]})
    digest = pending.digest(WB_PAYLOAD)
    wb = c["miworkbench"]
    assert await pending.open_id(wb, "steer_sweep", payload_digest=digest) is None
    assert (
        await pending.open_id(wb, "steer_sweep", payload_digest=digest, include_closed=True)
        == "req-1"
    )


async def test_midataworks_stores_the_body_under_its_parameter_with_enrichment_beside() -> None:
    """OR1-pb-10b: the stored payload is ``{"body": <the body>, <enrichment>}``
    (agent_origin.py:342-357), so the digest of the body matches one level deep."""
    body = {"version_id": "v1", "build_id": "b1", "repo_id": "o/r", "visibility": "private"}
    stored = {"body": body, "card_facts": {"rows": 10}}
    c, _ = await clients({"midataworks": [dw_row("apv-1", "pending", stored)]})
    dw = c["midataworks"]
    assert (await pending.open_id(dw, "hub_push", payload_digest=pending.digest(body))) == "apv-1"
    assert (
        await pending.open_id(dw, "hub_push", fields={"version_id": "v1", "repo_id": "o/r"})
        == "apv-1"
    )
    assert await pending.open_id(dw, "hub_push", fields={"version_id": "v2"}) is None


async def test_a_body_stored_with_defaults_filled_matches_on_the_keys_sent() -> None:
    """003's send: miDataworks fills defaults into the stored body, so the digest is taken over
    the keys the caller sent (``keys=``)."""
    sent = {"set_ids": ["dst_main"], "visibility": "private"}
    stored = {"body": {**sent, "namespace": None, "repositories": {}}, "sends": []}
    c, _ = await clients({"midataworks": [dw_row("apv-1", "pending", stored)]})
    dw = c["midataworks"]
    digest = pending.digest(sent)
    assert await pending.open_id(dw, "hub_push", payload_digest=digest) is None
    assert await pending.open_id(dw, "hub_push", payload_digest=digest, keys=tuple(sent)) == "apv-1"


async def test_miserver_rows_are_named_by_approval_id() -> None:
    c, _ = await clients(
        {"miserver": [sv_row("sv-1", "pending", {"model_id": 3, "request": None})]}
    )
    sv = c["miserver"]
    assert await pending.open_id(sv, "model_load", fields={"model_id": 3}) == "sv-1"
    assert await pending.open_id(sv, "model_load", remembered="sv-1") == "sv-1"


async def test_newest_match_first() -> None:
    rows = {
        "miworkbench": [
            wb_row("req-1", "pending", WB_PAYLOAD),
            wb_row("req-2", "pending", WB_PAYLOAD),
        ]
    }
    c, _ = await clients(rows)
    assert (
        await pending.open_id(
            c["miworkbench"], "steer_sweep", payload_digest=pending.digest(WB_PAYLOAD)
        )
        == "req-2"
    )


def test_needs_something_to_match_on() -> None:
    with pytest.raises(ValueError):
        import asyncio

        asyncio.run(pending.find_requests(None, "x", status="pending"))  # type: ignore[arg-type]
