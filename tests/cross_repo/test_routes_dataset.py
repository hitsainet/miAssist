"""The dataset playbook's routes against miDataworks' own code (004 FTASKS 7.1; FTID §10).

miDataworks' OpenAPI is regenerated in its own interpreter from a ``git archive`` of its committed
ref (``MIASSIST_SNAPSHOT_REF_MIDATAWORKS``, default ``HEAD``; nothing is written in the sibling).
Every route the playbook registers exists there with the method it is called with, and each
published gate marker classifies it exactly as the registry does (A19, A33). Skips loudly when the
sibling is absent; fails under ``MIASSIST_REQUIRE_CROSS_REPO_CHECKS=1``.
"""

from __future__ import annotations

import pytest
from scripts import snapshot_openapi as snap

from miassist.adapters.dataset import DATASET_ROUTES
from miassist.adapters.routes import classify_marker, when_tokens
from tests.cross_repo.test_openapi_live import regenerated

pytestmark = pytest.mark.cross_repo


def test_every_dataset_route_is_served() -> None:
    live = {
        (r["method"], r["path"]) for r in snap.route_index(regenerated("midataworks")["openapi"])
    }
    missing = [r.id for r in DATASET_ROUTES if (r.method, r.path) not in live]
    assert missing == [], f"miDataworks does not serve: {missing}"


def test_gate_markers_agree() -> None:
    paths = regenerated("midataworks")["openapi"]["paths"]
    for route in DATASET_ROUTES:
        op = paths[route.path][route.method.lower()]
        marked = classify_marker("midataworks", route.method, route.path, op)
        if marked is None:
            continue
        assert marked is route.gate, route.id
        assert route.gate_when == when_tokens(op) or not route.gate_when, route.id
