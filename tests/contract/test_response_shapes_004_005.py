"""The response-shape snapshot and its validator (R1 review fix OR1-pb-1..5, 2026-11-16; OVN-17).

Pins: every route miAssist registers has a typed answer in its app's snapshot (a new route with no
shape fails here, so its fakes cannot be hand-written); and the validator refuses each off-shape
answer review round 1 found in the 004/005 fakes.
"""

from __future__ import annotations

import json

import pytest

from miassist.adapters.routes import ROUTES
from tests.support import response_shapes as rs
from tests.support import shapes

APPS = ("midataworks", "miworkbench", "miserver")


@pytest.mark.parametrize("app", APPS)
def test_the_shapes_are_read_at_the_snapshot_commit(app: str) -> None:
    """One commit per app for the vendored shapes and the OpenAPI snapshot (003's rule too)."""
    assert rs.vendored()["apps"][app]["commit"] == rs.snapshot(app)["commit"]
    for key, statuses in rs.vendored()["apps"][app]["routes"].items():
        for status, entry in statuses.items():
            assert entry["source"].strip(), f"{key} {status}: every entry cites its source"


@pytest.mark.parametrize("app", APPS)
def test_every_registered_route_has_a_shape(app: str) -> None:
    """A route without a vendored success shape would let its fake invent the answer."""
    for route in ROUTES.for_app(app):
        key = f"{route.method} {route.path}"
        op = rs.snapshot(app)["paths"][route.path][route.method.lower()]
        success = [s for s in op["responses"] if s.startswith("2")]
        assert success, key
        found = [shapes.schema(app, key, int(s)) for s in success]
        assert any(
            f is not None for f in found
        ), f"{key}: no shape; python -m scripts.snapshot_shapes"


OFF_SHAPE = [
    # OR1-pb-1: the labelling facts at the top level, not under ``labelling``
    (
        "midataworks",
        "POST /api/v1/versions/plan",
        200,
        {"valid": True, "counted_steps": [], "rows_counted": 0, "agent_needs_approval": False},
    ),
    # OR1-pb-2: the task status as a string, not SteeringTaskStatus
    (
        "miworkbench",
        "GET /api/v1/steering/async/result/{task_id}",
        200,
        {"task_id": "t", "status": "success", "result": None},
    ),
    # OR1-pb-3: ``steered_output`` instead of ``combined_output``
    (
        "miworkbench",
        "GET /api/v1/steering/async/result/{task_id}",
        200,
        {
            "task_id": "t",
            "status": {"task_id": "t", "status": "success"},
            "result": {"steered_output": "x"},
        },
    ),
    # OR1-pb-4a: the import answering the cluster, not ClusterImportResult
    (
        "miserver",
        "POST /api/clusters/import",
        200,
        {"success": True, "data": {"id": "c", "name": "n", "model_id": "m", "sae_id": "s"}},
    ),
    # OR1-pb-4b: health ``loaded_model`` in a data envelope; ``active_profile`` a string
    (
        "miserver",
        "GET /api/health/detailed",
        200,
        {"success": True, "data": {"model": {"loaded_model": "m"}, "active_profile": "x"}},
    ),
    # OR1-pb-5: dict members, not (feature_idx, label, strength) triples
    (
        "miserver",
        "GET /api/clusters",
        200,
        {
            "success": True,
            "data": {
                "clusters": [
                    {
                        "id": "c",
                        "name": "n",
                        "is_active": False,
                        "intensity": 1.0,
                        "sensing_enabled": False,
                        "created_at": "2026-11-16T00:00:00Z",
                        "updated_at": "2026-11-16T00:00:00Z",
                        "members": [{"feature_idx": 1, "strength": 2.0}],
                    }
                ]
            },
        },
    ),
    # 004: a job ``succeeded`` (miDataworks says ``completed``)
    ("midataworks", "GET /api/v1/jobs/{job_id}", 200, None),
    # a 201 where the app answers 200
    ("midataworks", "POST /api/v1/sources/hf/search", 201, {}),
]


@pytest.mark.parametrize("app,key,status,body", OFF_SHAPE)
def test_the_validator_refuses_what_the_apps_never_send(
    app: str, key: str, status: int, body: object
) -> None:
    if body is None:
        body = shapes.instance(app, key, status, id="j", status="completed")
        body["status"] = "succeeded"
    elif isinstance(body, dict) and status in (200, 202):
        body = rs.fill(
            shapes.schema(app, key, status) or {}, body
        )  # complete the rest: only the defect remains
    assert shapes.violations(app, key, status, body), json.dumps(body)[:200]


def test_a_valid_answer_passes() -> None:
    body = shapes.instance("midataworks", "GET /api/v1/jobs/{job_id}", 200, status="completed")
    assert shapes.violations("midataworks", "GET /api/v1/jobs/{job_id}", 200, body) == []


def test_an_invented_field_is_refused_even_when_everything_else_fits() -> None:
    """Objects are closed: ``steered_output`` beside a valid answer is still a violation (control
    F08)."""
    key = "GET /api/v1/jobs/{job_id}"
    body = shapes.instance("midataworks", key, 200, status="completed")
    assert shapes.violations("midataworks", key, 200, body) == []
    assert shapes.violations("midataworks", key, 200, {**body, "steered_output": "x"})
