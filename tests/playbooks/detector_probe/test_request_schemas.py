"""The vendored request schemas Core's pre-filing check reads in production (OVN-miassist-pb003-1)."""

from __future__ import annotations

from scripts import write_request_schemas

from miassist.adapters.routes import ROUTES
from miassist.playbooks.detector_probe import routes as rt
from miassist.vendored import requests as vendored


def test_vendored_file_equals_a_fresh_derivation() -> None:
    assert write_request_schemas.TARGET.read_text() == write_request_schemas.text()


def test_every_file_first_route_has_a_schema() -> None:
    for route in ROUTES:
        if route.file_first:
            schema = vendored.lookup(route)
            assert schema is not None and schema.body is not None, route.id


def test_an_unknown_route_has_none() -> None:
    reads = [r for r in ROUTES if not r.file_first]
    assert all(vendored.lookup(r) is None for r in reads)


def test_refusals_follow_the_apps_request_schema() -> None:
    """R1 review fix (OR1-pb-7), 2026-11-16: what miWorkbench's own schema refuses (a bound, a
    type, an undeclared query name, a required body) is named before anything is filed."""
    assert vendored.refusals(rt.PROBE_EVALUATE, {"sample_rows": 20_000}, ["evalfx-view-1"]) == []
    low = vendored.refusals(rt.PROBE_EVALUATE, {"sample_rows": 50}, ["evalfx-view-1"])
    assert low and low[0].startswith("query.sample_rows:")
    assert vendored.refusals(rt.PROBE_EVALUATE, {"limit": 5}, []) == ["query.limit: not declared"]
    assert vendored.refusals(rt.PROBE_EVALUATE, {}, [3])[0].startswith("body.0:")
    assert vendored.refusals(rt.PROBE_RUNS, {}, None), "the run body is required"
    run = {"model_id": "m", "train_dataset_id": "v", "config": {"stride": 0}}
    assert vendored.refusals(rt.PROBE_RUNS, {}, run)[0].startswith("body.config.stride:")
