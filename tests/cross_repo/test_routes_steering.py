"""The steering playbook's routes against miWorkbench's and miServer's own code (005 FTASKS 7.1).

Each app's OpenAPI is regenerated in its own interpreter from a ``git archive`` of its committed ref
(``MIASSIST_SNAPSHOT_REF_<APP>``, default ``HEAD``). Every steering route, the two GPU routes
included, is served; the pinned request schemas of the GPU routes equal miWorkbench's. Skips
loudly when a sibling is absent; fails under ``MIASSIST_REQUIRE_CROSS_REPO_CHECKS=1``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from scripts import snapshot_openapi as snap

from miassist.adapters.steering import GPU_ROUTES, STEERING_ROUTES
from tests.cross_repo.test_openapi_live import regenerated

pytestmark = pytest.mark.cross_repo


@pytest.mark.parametrize("app", ["miworkbench", "miserver"])
def test_every_steering_route_is_served(app: str) -> None:
    live = {(r["method"], r["path"]) for r in snap.route_index(regenerated(app)["openapi"])}
    mine = [r for r in (*STEERING_ROUTES, *GPU_ROUTES) if r.app == app]
    assert mine
    assert [r.id for r in mine if (r.method, r.path) not in live] == []


def test_gpu_request_schemas_are_miworkbenchs() -> None:
    api = regenerated("miworkbench")["openapi"]
    comps = api.get("components", {}).get("schemas", {})
    pinned = json.loads(
        (
            Path(__file__).resolve().parents[1] / "playbooks/steering/gpu_request_schemas.json"
        ).read_text()
    )["routes"]
    for route in GPU_ROUTES:
        op = api["paths"][route.path]["post"]
        body = (
            op.get("requestBody", {}).get("content", {}).get("application/json", {}).get("schema")
        )
        query = sorted(p["name"] for p in op.get("parameters", []) if p.get("in") == "query")
        assert pinned[f"POST {route.path}"] == {
            "query": query,
            "body": snap.resolve(body, comps),
        }, route.id
