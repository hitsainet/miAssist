"""R2M-7, R3M-13: Core's id_filter_vectors.json through 002's recorder gives Core's verdict on
every vector, and 002's objects ARE Core's (function-object identity)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from miassist_eval import allowed, classes
from miassist_eval.recorder import Recorder
from tests.support import harness

VECTORS = Path(__file__).resolve().parents[3] / "tests/fixtures/id_filter_vectors.json"


def table() -> dict:
    if not VECTORS.is_file():
        pytest.skip(f"LOUD SKIP: Core's {VECTORS} is absent (push 001-A)")
    return json.loads(VECTORS.read_text())


def test_identity_with_cores_module() -> None:
    import miassist_fixtures.filter as core

    assert allowed.AllowedSet is core.AllowedSet
    assert allowed.filter_list is core.filter_list
    assert allowed.final_scan is core.final_scan


def _allowed_set(doc: dict):
    fx = doc["fixtures"]
    return allowed.AllowedSet(
        prefix=fx["prefix"], ids=set(fx["ids"]), repositories=set(fx["public_repositories"])
    )


@pytest.mark.parametrize("vector", table()["vectors"], ids=lambda v: v["id"])
async def test_vector_through_the_recorder(vector: dict) -> None:
    """Each vector's request goes through 002's recorder ``check_request`` call path."""
    doc = table()
    forwarded = []

    async def forward(*a):
        forwarded.append(a)
        return 200, {}, {}

    edge = harness.edge("baseline")  # no header rule: the vector is about ids only
    rec = Recorder(
        edge=edge, forward=forward, allowed_set=_allowed_set(doc), app_versions={}, writing=False
    )
    req = vector["request"]
    prof = vector["profile"]
    try:
        rec.allowed_set.check_request(
            allowed.core_profile({"creates": prof.get("creates", False)}, prof["template"]),
            {"path": req["path"], "query": req.get("query") or {}, "body": req.get("body")},
        )
        verdict, at = "allowed", None
    except allowed.FixtureRefused as exc:
        verdict, at = "refused", exc.where
    assert (verdict, at) == (vector["verdict"], vector["refused_at"])


async def test_the_recorder_refuses_core_refused_vector_end_to_end() -> None:
    """One vector through Recorder.handle, on a route the reference has (eval_dataset_ids)."""
    doc = table()
    forwarded = []

    async def forward(*a):
        forwarded.append(a)
        return 200, {}, {}

    rec = Recorder(
        edge=harness.edge("baseline"),
        forward=forward,
        allowed_set=_allowed_set(doc),
        app_versions={},
        writing=True,
    )
    status, _, body = await rec.handle(
        "midataworks",
        "POST",
        "/api/v1/label-runs",
        {},
        {},
        {"eval_dataset_ids": ["evalfx-a", "prod-7"]},
    )
    assert status == 403 and body["refused"] == classes.FIXTURE_NOT_ALLOWED
    assert body["at"] == "body.eval_dataset_ids[1]" and forwarded == []
