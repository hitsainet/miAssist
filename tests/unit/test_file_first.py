"""File first on miWorkbench's GPU routes (A18, A29, A32, A38, A40; 001 FTASKS 5.2).

The fixture GPU route is served by a fake WITH NO GATE OF ITS OWN: everything that keeps it from
running unapproved is miAssist's.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from miassist.adapters.base import (
    APPROVAL_ID_HEADER,
    GateClass,
    Pending,
    ProgrammingError,
    Resource,
    Route,
)
from miassist.adapters.miworkbench import RequestSchema, WorkbenchAdapter, canonical_payload
from miassist.adapters.routes import RouteRegistry
from miassist.errors import MiAssistError
from tests.support.clients import client_for, test_registry
from tests.support.fake_apps import FakeApp, Recorded
from tests.support.vectors import VECTORS_FILE

GPU = "/api/v1/fixture/probe-runs/{probe_id}/start"
ACTION = "start_probe_training_run"
SCHEMA = RequestSchema(
    query=frozenset({"sample_rows"}),
    body={
        "anyOf": [
            {"type": "array", "items": {"type": "string"}},
            {
                "type": "object",
                "properties": {
                    "dataset_id": {"type": "string"},
                    "config": {"type": "object", "properties": {"epochs": {"type": "integer"}}},
                    "acknowledge_below_rung2": {"type": "object", "additionalProperties": True},
                },
            },
        ]
    },
)


class Queue:
    """miWorkbench's approval queue, faked."""

    def __init__(self, fake: FakeApp) -> None:
        self.rows: dict[str, dict[str, Any]] = {}
        self.filings: list[dict[str, Any]] = []
        fake.on("GET", "/api/v1/mcp/approvals", lambda r: {"approvals": [], "total": 0})
        fake.on("POST", "/api/v1/mcp/approvals", self.file)
        fake.on("GET", "/api/v1/mcp/approvals/{request_id}", self.read)

    def file(self, request: Recorded) -> dict[str, Any]:
        row_id = f"ap{len(self.rows) + 1}"
        self.filings.append(request.body)
        self.rows[row_id] = {
            "id": row_id,
            "status": "pending",
            "tool_name": request.body["tool_name"],
            "requested_by": "miassist",
            "payload": request.body["payload"],
        }
        return {"id": row_id, "status": "pending"}

    def read(self, request: Recorded) -> httpx.Response | dict[str, Any]:
        row = self.rows.get(request.path_params["request_id"])
        if row is None:
            return httpx.Response(404, json={"detail": "not found"})
        return row


def setup(route_answer: Any = None) -> tuple[FakeApp, Queue, WorkbenchAdapter]:
    fake = FakeApp("miworkbench")
    queue = Queue(fake)
    fake.on("POST", GPU, route_answer if route_answer is not None else {"task_id": "t1"})
    registry = test_registry()
    adapter = WorkbenchAdapter(client_for(fake, registry=registry), lambda _route: SCHEMA)
    return fake, queue, adapter


def route() -> Any:
    return test_registry().get("miworkbench.fixture_start_gpu_job")


async def call(adapter: WorkbenchAdapter, approval_id: str | None = None, **over: Any) -> Any:
    kwargs: dict[str, Any] = {
        "path_params": {"probe_id": "p1"},
        "query": {"sample_rows": 50},
        "body": {"dataset_id": "d1"},
        "tool": "miassist_fixture_train",
        "args": {"probe": "p1"},
        "summary": "Train the probe on the GPU(s) available.",
    }
    kwargs.update(over)
    gpu = adapter.client.guards.registry.get("miworkbench.fixture_start_gpu_job")
    return await adapter.file_first(gpu, approval_id=approval_id, **kwargs)


async def test_first_call_files_only() -> None:
    fake, queue, adapter = setup()
    answer = await call(adapter)
    assert isinstance(answer, Pending)
    assert answer.approval["then"] == "call_again_with"
    assert len(fake.calls("POST", "/api/v1/mcp/approvals")) == 1
    assert queue.filings[0] == {
        "tool_name": ACTION,
        "payload": {
            "_method": "POST",
            "_route": GPU,
            "probe_id": "p1",
            "sample_rows": 50,
            "dataset_id": "d1",
        },
    }
    assert fake.calls("POST", GPU) == []


async def test_call_again_with_present() -> None:
    _, _, adapter = setup()
    answer = await call(adapter)
    assert answer.approval["call_again_with"] == {
        "tool": "miassist_fixture_train",
        "args": {"probe": "p1", "approval_id": "ap1"},
    }


async def test_recall_reads_status_then_calls_once() -> None:
    fake, queue, adapter = setup()
    await call(adapter)
    queue.rows["ap1"]["status"] = "approved"
    answer = await call(adapter, approval_id="ap1")
    assert isinstance(answer, Resource)
    assert len(fake.calls("GET", "/api/v1/mcp/approvals/{request_id}")) == 1
    (sent,) = fake.calls("POST", GPU)
    assert sent.headers[APPROVAL_ID_HEADER.lower()] == "ap1"
    assert sent.params == {"sample_rows": "50"} and sent.body == {"dataset_id": "d1"}
    assert canonical_payload("POST", GPU, {"probe_id": "p1"}, {"sample_rows": 50}, sent.body) == (
        queue.rows["ap1"]["payload"]
    )


@pytest.mark.parametrize("status", ["pending", "denied", "expired", "consumed", "failed"])
async def test_not_approved_never_reaches_route(status: str) -> None:
    fake, queue, adapter = setup()
    await call(adapter)
    queue.rows["ap1"]["status"] = status
    answer = await call(adapter, approval_id="ap1")
    assert isinstance(answer, Pending)
    assert fake.calls("POST", GPU) == []


@pytest.mark.parametrize(
    ("field", "value"), [("tool_name", "start_probe_judge_run"), ("requested_by", "someone-else")]
)
async def test_provenance(field: str, value: str) -> None:
    fake, queue, adapter = setup()
    await call(adapter)
    queue.rows["ap1"].update(status="approved", **{field: value})
    with pytest.raises(MiAssistError) as caught:
        await call(adapter, approval_id="ap1")
    assert caught.value.code == "approval_mismatch"
    assert fake.calls("POST", GPU) == []


async def test_call_refuses_file_first_without_approved_id() -> None:
    fake, _, adapter = setup()
    with pytest.raises(ProgrammingError):
        await adapter.client.call(route(), path_params={"probe_id": "p1"}, json={})
    with pytest.raises(ProgrammingError):
        await adapter.client.call(
            adapter.client.guards.registry.get("miworkbench.fixture_start_gpu_job"),
            path_params={"probe_id": "p1"},
            json={},
        )
    assert fake.calls("POST", GPU) == []


async def test_never_calls_consume() -> None:
    fake, queue, adapter = setup()
    await call(adapter)
    queue.rows["ap1"]["status"] = "approved"
    await call(adapter, approval_id="ap1")
    assert not [r for r in fake.requests if r.path.endswith("/consume")]


async def test_over_wide_body_is_refused_before_filing() -> None:
    fake, _, adapter = setup()
    with pytest.raises(MiAssistError) as caught:
        await call(adapter, body={"dataset_id": "d1", "config": {"epochs": 2, "lr": 0.1}})
    assert caught.value.code == "invalid_arguments"
    assert fake.calls("POST", "/api/v1/mcp/approvals") == []


async def test_mapping_field_is_open() -> None:
    _, queue, adapter = setup()
    answer = await call(
        adapter,
        body={"dataset_id": "d1", "acknowledge_below_rung2": {"why": "x"}},
        person_reason="I accept the lower bar",
    )
    assert isinstance(answer, Pending) and queue.filings


@pytest.mark.parametrize(
    ("status", "code", "expected"),
    [
        (409, "consumed", "approval_spent"),
        (404, "not_found", "approval_not_found"),
        (422, "mismatch", "approval_mismatch"),
    ],
)
async def test_route_refusals_raised(status: int, code: str, expected: str) -> None:
    fake = FakeApp("miworkbench")
    responses = {"answer": fake.error(status, code)}
    _fake2, queue, adapter = setup(lambda r: responses["answer"])
    await call(adapter)
    queue.rows["ap1"]["status"] = "approved"
    with pytest.raises(MiAssistError) as caught:
        await call(adapter, approval_id="ap1")
    assert caught.value.code == expected


@pytest.mark.parametrize(
    "code", ["unknown_body_field", "unknown_query_field", "approval_not_applicable"]
)
async def test_route_422_codes(code: str) -> None:
    fake = FakeApp("miworkbench")
    _fake2, queue, adapter = setup(lambda r: fake.error(422, code))
    await call(adapter)
    queue.rows["ap1"]["status"] = "approved"
    answer = await call(adapter, approval_id="ap1")
    assert answer.code == f"miworkbench.{code}"


async def test_422_without_code_is_invalid_body() -> None:
    _, queue, adapter = setup(lambda r: httpx.Response(422, json={"detail": [{"msg": "x"}]}))
    await call(adapter)
    queue.rows["ap1"]["status"] = "approved"
    answer = await call(adapter, approval_id="ap1")
    assert answer.code == "miworkbench.invalid_body"


async def test_failed_after_consume_is_terminal() -> None:
    """A40: the handler refused after the consume; the re-read shows failed; nothing re-filed."""
    fake = FakeApp("miworkbench")
    holder: dict[str, Queue] = {}

    def refuse(_: Recorded) -> httpx.Response:
        holder["q"].rows["ap1"]["status"] = "failed"
        return fake.error(409, "model_files_not_on_disk", "no weights")

    fake2, queue, adapter = setup(refuse)
    holder["q"] = queue
    await call(adapter)
    queue.rows["ap1"]["status"] = "approved"
    answer = await call(adapter, approval_id="ap1")
    assert isinstance(answer, Pending) and answer.approval["status"] == "failed"
    assert answer.approval["reason"] == "no weights", "a terminal failed loses the app's reason"
    assert len(fake2.calls("GET", "/api/v1/mcp/approvals/{request_id}")) == 2
    assert len(queue.filings) == 1, "a failed approval was re-filed"


@pytest.mark.parametrize("status,contract", [("denied", "rejected"), ("expired", "expired")])
async def test_refusal_then_terminal_status_maps_to_that_status(status: str, contract: str) -> None:
    """R2 review fix (OR2-001-7, M-13): the route refused and the re-read shows ``denied`` (or
    ``expired``): the answer is that status (in the contract's word), not the route's own
    refusal code (here ``consumed``, which would otherwise raise ``approval_spent``)."""
    fake = FakeApp("miworkbench")
    holder: dict[str, Queue] = {}

    def refuse(_: Recorded) -> httpx.Response:
        holder["q"].rows["ap1"]["status"] = status
        return fake.error(409, "consumed", "already used")

    fake2, queue, adapter = setup(refuse)
    holder["q"] = queue
    await call(adapter)
    queue.rows["ap1"]["status"] = "approved"
    answer = await call(adapter, approval_id="ap1")
    assert isinstance(answer, Pending) and answer.approval["status"] == contract
    assert len(fake2.calls("GET", "/api/v1/mcp/approvals/{request_id}")) == 2
    assert len(queue.filings) == 1


def vector(action: str) -> dict[str, Any]:
    vectors = json.loads(VECTORS_FILE.read_text())["vectors"]
    found: dict[str, Any] = next(v for v in vectors if v["action"] == action)
    return found


async def file_vector(action: str, body_param: str | None = None) -> tuple[Any, Queue, FakeApp]:
    """File the vector's own request through ``file_first`` on a route with the vector's path."""
    v = vector(action)
    fake = FakeApp("miworkbench")
    queue = Queue(fake)
    fake.on("POST", v["route"], {"task_id": "t1"})
    shaped = Route(
        id=f"miworkbench.vector_{action}",
        app="miworkbench",
        method=v["method"],
        path=v["route"],
        gate=GateClass.APP_GATED,
        purpose="the vector's route (test registry only)",
        file_first=True,
        approval_action=action,
    )
    registry = RouteRegistry((*test_registry(), shaped))
    open_schema = RequestSchema(
        query=frozenset(v["request"]["query"]),
        body={"anyOf": [{"type": "array"}, {"type": "object", "additionalProperties": True}]},
    )
    adapter = WorkbenchAdapter(client_for(fake, registry=registry), lambda _route: open_schema)
    params = {k: val for k, val in v["payload"].items() if "{" + k + "}" in v["route"]}
    kwargs: dict[str, Any] = {
        "path_params": params,
        "query": v["request"]["query"],
        "body": v["request"]["body"],
        "tool": "miassist_fixture_vector",
        "args": {},
        "summary": "A vector's request.",
    }
    if body_param:
        kwargs["body_param"] = body_param
    answer = await adapter.file_first(shaped, approval_id=None, **kwargs)
    return answer, queue, fake


async def test_shapes_array_body_query_path() -> None:
    """003's evaluate shape (the id in the path, a bare array body): the filed payload is 045's
    vector for ``evaluate_probe_monitor`` (5.2a replaces 5.2's provisional expectation)."""
    answer, queue, _ = await file_vector("evaluate_probe_monitor", body_param="dataset_ids")
    assert isinstance(answer, Pending)
    assert queue.filings[0] == {
        "tool_name": "evaluate_probe_monitor",
        "payload": vector("evaluate_probe_monitor")["payload"],
    }


async def test_shapes_path_only() -> None:
    """The definition build (path only): the filed payload is 045's ``build_probe_definition``
    vector."""
    answer, queue, _ = await file_vector("build_probe_definition")
    assert isinstance(answer, Pending)
    assert queue.filings[0]["payload"] == vector("build_probe_definition")["payload"]


async def test_shapes_query_and_array_body_still_split() -> None:
    """NC-A37-4's case kept from 5.2: the route call carries the parts as given, never one flat
    object (the filing is the flat form; the call is not)."""
    fake, queue, adapter = setup()
    await call(adapter, body=["d1", "d2"], body_param="dataset_ids")
    queue.rows["ap1"]["status"] = "approved"
    await call(adapter, approval_id="ap1", body=["d1", "d2"], body_param="dataset_ids")
    (sent,) = fake.calls("POST", GPU)
    assert sent.body == ["d1", "d2"] and sent.params == {"sample_rows": "50"}


def test_canonical_drops_the_id() -> None:
    assert "approval_request_id" not in canonical_payload(
        "post", "/x/{a}", {"a": 1}, {}, {"approval_request_id": "z", "k": 2}
    )
