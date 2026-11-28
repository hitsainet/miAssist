"""FR-002.9, FR-002.11, FR-002.20: match keys, echoes, sequences, cassette_miss naming the field,
unknown_route, the approval hold and its release through the control port only."""

from __future__ import annotations

import httpx

from miassist_eval import classes, replay
from tests.support import harness

DW = harness.HEADERS["midataworks"]
WB = harness.HEADERS["miworkbench"]


def rep(records) -> replay.Replay:
    return replay.build(
        harness.cassette_doc(records), harness.edge(), {"midataworks": {"status": "ok"}}
    )


def job(seq: int, status: str) -> dict:
    return harness.record(
        seq,
        "midataworks",
        "GET",
        "/api/v1/jobs/evalfx-j",
        "/api/v1/jobs/{job_id}",
        200,
        {"id": "evalfx-j", "status": status},
    )


def test_a_matching_request_gets_the_recorded_answer() -> None:
    r = rep(
        [
            harness.record(
                0,
                "midataworks",
                "POST",
                "/api/v1/label-runs",
                "/api/v1/label-runs",
                202,
                {"job_id": "evalfx-j"},
                req_body={"dataset_id": "evalfx-ds", "n": 3},
            )
        ]
    )
    status, _, body = r.handle(
        "midataworks", "POST", "/api/v1/label-runs", {}, DW, {"n": 3, "dataset_id": "evalfx-ds"}
    )
    assert (status, body) == (202, {"job_id": "evalfx-j"})
    assert r.state.effects.lines[-1]["sequence_index"] == 0


def test_a_differing_body_field_is_a_cassette_miss_naming_it() -> None:
    r = rep(
        [
            harness.record(
                0,
                "midataworks",
                "POST",
                "/api/v1/label-runs",
                "/api/v1/label-runs",
                202,
                {"job_id": "evalfx-j"},
                req_body={"dataset_id": "evalfx-ds", "n": 3},
            )
        ]
    )
    status, _, body = r.handle(
        "midataworks", "POST", "/api/v1/label-runs", {}, DW, {"dataset_id": "evalfx-ds", "n": 4}
    )
    assert status == 503
    assert body["cassette_miss"]["differs"] == ["body.n"]
    assert r.state.failures == [(classes.OFF_RECORDING, "POST /api/v1/label-runs: ['body.n']")]


def test_an_unknown_route_is_404() -> None:
    status, _, body = rep([]).handle("midataworks", "GET", "/api/v1/not-a-route", {}, DW, None)
    assert status == 404 and "unknown_route" in body


def test_status_reads_advance_and_the_last_repeats() -> None:
    r = rep([job(0, "queued"), job(1, "running"), job(2, "completed")])
    states = [
        r.handle("midataworks", "GET", "/api/v1/jobs/evalfx-j", {}, DW, None)[2]["status"]
        for _ in range(5)
    ]
    assert states == ["queued", "running", "completed", "completed", "completed"]


def approval(seq: int, status: str) -> dict:
    return harness.record(
        seq,
        "midataworks",
        "GET",
        "/api/v1/approvals/evalfx-a",
        "/api/v1/approvals/{approval_id}",
        200,
        {"id": "evalfx-a", "status": status},
    )


def test_an_approval_holds_until_released() -> None:
    r = rep([approval(0, "pending"), approval(1, "pending"), approval(2, "executed")])
    reads = [
        r.handle("midataworks", "GET", "/api/v1/approvals/evalfx-a", {}, DW, None)[2]["status"]
        for _ in range(4)
    ]
    assert reads == ["pending", "pending", "pending", "pending"]
    r.state.released.add(("midataworks", "evalfx-a"))
    assert (
        r.handle("midataworks", "GET", "/api/v1/approvals/evalfx-a", {}, DW, None)[2]["status"]
        == "executed"
    )


async def test_release_only_through_the_control_app() -> None:
    r = rep([approval(0, "pending"), approval(1, "executed")])
    app_transport = httpx.ASGITransport(app=r.app_for("midataworks"))
    async with httpx.AsyncClient(transport=app_transport, base_url="http://dw") as client:
        resp = await client.post("/release/midataworks/evalfx-a", headers=DW)
        assert resp.status_code == 404, "the app listener exposes the control route"
    assert r.state.released == set()
    control = httpx.ASGITransport(app=r.control_app())
    async with httpx.AsyncClient(transport=control, base_url="http://ctl") as client:
        assert (await client.post("/release/midataworks/evalfx-a")).status_code == 200
    assert r.state.released == {("midataworks", "evalfx-a")}


def test_echo_fields_are_left_out_of_the_match_and_substituted() -> None:
    edge = harness.edge()
    prof = edge.profiles["midataworks"]
    entry = next(
        x for x in prof["routes"] if x["route"] == "/api/v1/datasets" and x["method"] == "POST"
    )
    entry["echo"] = ["body.name"]
    take = harness.cassette_doc(
        [
            harness.record(
                0,
                "midataworks",
                "POST",
                "/api/v1/datasets",
                "/api/v1/datasets",
                201,
                {"id": "evalfx-ds-9", "name": "evalfx-refunds"},
                req_body={"name": "evalfx-refunds", "kind": "x"},
            )
        ]
    )
    r = replay.build(take, edge, {})
    status, _, body = r.handle(
        "midataworks",
        "POST",
        "/api/v1/datasets",
        {},
        DW,
        {"name": "evalfx-my-own-name", "kind": "x"},
    )
    assert status == 201 and body["name"] == "evalfx-my-own-name"
    assert r.state.effects.lines[-1]["echoes"] == ["body.name"]


def test_health_and_openapi_are_answered() -> None:
    r = rep([])
    assert r.handle("midataworks", "GET", "/api/health", {}, DW, None) == (
        200,
        {},
        {"status": "ok"},
    )
    assert r.handle("midataworks", "GET", "/openapi.json", {}, DW, None)[2]["paths"]


def test_the_effects_log_records_every_request_in_order() -> None:
    r = rep([job(0, "queued"), job(1, "completed")])
    r.handle("midataworks", "GET", "/api/v1/jobs/evalfx-j", {}, DW, None)
    r.handle("midataworks", "GET", "/api/v1/jobs/evalfx-j", {}, DW, None)
    r.handle("midataworks", "GET", "/api/v1/nope", {}, DW, None)
    lines = r.state.effects.lines
    assert [(x["path"], x["status"]) for x in lines] == [
        ("/api/v1/jobs/evalfx-j", 200),
        ("/api/v1/jobs/evalfx-j", 200),
        ("/api/v1/nope", 404),
    ]
    assert all("request_body_sha256" in x for x in lines)
