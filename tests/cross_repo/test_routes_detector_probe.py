"""003's routes against each sibling's served OpenAPI (FPRD §6, §7; FTID §8; FTASKS 8.1).

Regenerated in the sibling's own interpreter (Core's ``regenerated``); every detector route must
be served with its method, and every field miAssist sends must be declared by the route's request
schema. Skips loudly when a sibling is absent; fails under the require switch.
"""

from __future__ import annotations

from typing import Any

import pytest
from scripts import snapshot_openapi as snap

from miassist.adapters.miworkbench import undeclared_keys
from miassist.playbooks.detector_probe import routes as rt
from tests.cross_repo.test_openapi_live import regenerated

pytestmark = pytest.mark.cross_repo

#: The fields each write sends (FPRD §7), checked against the live request schema.
SENT: dict[str, dict[str, Any]] = {
    rt.BEHAVIOURS_CREATE.id: {
        "key": "k",
        "name": "n",
        "description": "d",
        "positive_meaning": "p",
        "negative_meaning": "q",
        "target_fpr": 0.01,
    },
    rt.PROBE_VIEWS_CREATE.id: {
        "dataset_id": "d",
        "name": "n",
        "input_column": "t",
        "label_column": "l",
        "split": "s",
        "role": "train",
        "distribution": "in_distribution",
        "behaviour": "k",
        "positive_meaning": "p",
        "config": "c",
        "label_mapping": {"a": "positive"},
    },
    rt.NONSENSE_TEXT.id: {"name": "n", "rows": 2000, "seed": 0, "register_view": True},
    rt.DATASET_DOWNLOAD.id: {"repo_id": "o/n", "config": "c"},
    rt.DW_DETECTOR_SETS_SEND.id: {"set_ids": ["s"], "visibility": "private"},
}


@pytest.mark.parametrize("route", rt.DETECTOR_ROUTES, ids=lambda r: r.id)
def test_route_is_served(route: Any) -> None:
    served = regenerated(route.app)["openapi"]["paths"]
    assert route.method.lower() in served.get(route.path, {}), f"{route.id} is not served"


@pytest.mark.parametrize("route_id", sorted(SENT))
def test_sent_fields_are_declared(route_id: str) -> None:
    route = next(r for r in rt.DETECTOR_ROUTES if r.id == route_id)
    openapi = regenerated(route.app)["openapi"]
    op = openapi["paths"][route.path][route.method.lower()]
    components = openapi.get("components", {}).get("schemas", {})
    schema = snap.resolve(op["requestBody"]["content"]["application/json"]["schema"], components)
    assert undeclared_keys(SENT[route_id], schema) == []
