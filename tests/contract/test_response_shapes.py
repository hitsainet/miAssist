"""The vendored response shapes the playbooks' fakes are checked against (R1 review fix OR1-pb-6 to
OR1-pb-9, 2026-11-16; ``tests/support/response_shapes.py``, ``tests/fixtures/openapi/responses.json``).
"""

from __future__ import annotations

from typing import Any

import pytest

from miassist.playbooks.detector_probe.routes import DETECTOR_ROUTES
from tests.support.response_shapes import (
    check,
    concrete,
    example,
    fill,
    openapi_schema,
    schema_for,
    snapshot,
    vendored,
)

APPS = ("miworkbench", "midataworks", "miserver")


@pytest.mark.parametrize("app", APPS)
def test_each_app_shapes_are_read_at_the_snapshot_commit(app: str) -> None:
    """The hand-derived shapes and the OpenAPI snapshot come from ONE commit of the app."""
    assert vendored()["apps"][app]["commit"] == snapshot(app)["commit"]


def _entries() -> list[tuple[str, str, str, str]]:
    return [
        (app, route.split(" ", 1)[0], route.split(" ", 1)[1], status)
        for app, data in vendored()["apps"].items()
        for route, statuses in data["routes"].items()
        for status in statuses
    ]


@pytest.mark.parametrize(("app", "method", "template", "status"), _entries())
def test_a_hand_derived_shape_names_the_openapi_fields(
    app: str, method: str, template: str, status: str
) -> None:
    """Where the app's OpenAPI names the fields, the hand-derived entry names the same top-level
    fields; it may only make an open part precise (``data: Any``, ``selection: dict``)."""
    entry = vendored()["apps"][app]["routes"][f"{method} {template}"][status]
    assert entry["source"].strip(), "every entry cites the app code it was read from"
    found = openapi_schema(app, method, template, status)
    if not concrete(found) or not isinstance(found.get("properties"), dict):
        return
    if found.get("title") == "HTTPValidationError":
        # FastAPI's generated 422 documents request validation only. miWorkbench's handlers also
        # raise HTTPException(422, ...) (still ``{"detail": ...}``); miDataworks and miServer answer
        # through their own exception handlers (their error envelopes, cited in the entry).
        if app == "miworkbench":
            branches = entry["schema"].get("anyOf", [entry["schema"]])
            assert all(set(b.get("properties", {})) == {"detail"} for b in branches)
        return
    mine = entry["schema"]
    branches = mine.get("anyOf", [mine])
    assert any(set(b.get("properties", {})) == set(found["properties"]) for b in branches)


@pytest.mark.parametrize("route", DETECTOR_ROUTES, ids=lambda r: r.id)
def test_every_detector_route_has_the_apps_success_shape(route: Any) -> None:
    """A route 003 calls without a vendored success shape would let its fake invent the answer."""
    op = snapshot(route.app)["paths"][route.path][route.method.lower()]
    success = sorted(s for s in op["responses"] if s.startswith("2"))
    assert success, route.id
    assert any(schema_for(route.app, route.method, route.path, s) is not None for s in success)


SHAPE: dict[str, Any] = {
    "type": "object",
    "properties": {
        "id": {"type": "string"},
        "state": {"enum": ["queued", "completed"]},
        "selection": {
            "anyOf": [
                {"type": "null"},
                {
                    "type": "object",
                    "properties": {"selected": {"type": ["string", "null"]}},
                    "required": ["selected"],
                    "additionalProperties": False,
                },
            ]
        },
        "counts": {"type": "object", "additionalProperties": True},
    },
    "required": ["id", "state", "selection", "counts"],
    "additionalProperties": False,
}


def test_the_check_names_an_invented_a_dropped_and_a_wrong_field() -> None:
    good = {"id": "x", "state": "queued", "selection": {"selected": "p"}, "counts": {"rows": 1}}
    assert check(SHAPE, good) == []
    assert check(SHAPE, {**good, "selected_probe_id": "p"}) == [
        "$.selected_probe_id: invented (the app never sends it)"
    ]
    dropped = {k: v for k, v in good.items() if k != "counts"}
    assert check(SHAPE, dropped) == ["$.counts: dropped (the app always sends it)"]
    assert check(SHAPE, {**good, "state": "refused"})[0].startswith("$.state: 'refused'")
    assert check(SHAPE, {**good, "id": 7})[0].startswith("$.id: int")
    assert check(SHAPE, {**good, "selection": {"selected_probe_id": "p"}})[0].startswith(
        "$.selection: matches no branch"
    )


def test_fill_adds_what_the_app_always_sends_and_keeps_inventions() -> None:
    filled = fill(SHAPE, {"id": "x", "selection": {}, "made_up": 1})
    assert filled["state"] == "queued" and filled["counts"] == {}
    assert filled["selection"] == {"selected": None}
    assert check(SHAPE, filled) == ["$.made_up: invented (the app never sends it)"]
    assert check(SHAPE, example(SHAPE)) == []


def test_a_response_model_sends_every_field() -> None:
    """A concrete OpenAPI schema is read as sent: a field with a default is still always there."""
    run = schema_for("miworkbench", "GET", "/api/v1/probe-monitors/runs/{run_id}", 200)
    assert "selection" in run["required"] and run["additionalProperties"] is False
