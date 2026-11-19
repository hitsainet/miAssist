"""Every fake answer must be one the real app can give (R1 review fixes OR1-pb-1 to OR1-pb-5,
2026-11-16; OVN-17). A thin layer over the suite's ONE shape format, 003's
``tests/support/response_shapes.py``: a route's shape is ``tests/fixtures/openapi/responses.json``
(hand- or generator-derived, each entry citing its source) or else the OpenAPI snapshot's response
model, read as SENT (every field present, objects closed).

``ShapedFakeApp`` checks EVERY 2xx answer a fake gives: the route and status must have a vendored
shape (a fake answering anything else is inventing it) and the answer must pass
``response_shapes.check`` (no invented field, none dropped, types and enums the app's). Violations
are collected (a raise inside the transport would surface as an unreachable app) and each
playbook's ``conftest.py`` fails the test at teardown. ``instance``/``fill`` build valid answers.
"""

from __future__ import annotations

import json
from typing import Any

import httpx

from tests.support import response_shapes as rs
from tests.support.fake_apps import FakeApp, Recorded

#: Every ShapedFakeApp made in this process; the conftest fixtures read and clear it.
LIVE: list[ShapedFakeApp] = []


def schema(app: str, key: str, status: int) -> Any | None:
    method, template = key.split(" ", 1)
    return rs.schema_for(app, method, template, status)


def violations(app: str, key: str, status: int, body: Any) -> list[str]:
    """What is wrong with ``body`` as the ``status`` answer of ``key`` (``"METHOD /path"``)."""
    found = schema(app, key, status)
    if found is None:
        return [f"{app} {key} {status}: no vendored shape (the fake would be inventing it)"]
    return [f"{app} {key} {status} {v}" for v in rs.check(found, body)]


class ShapedFakeApp(FakeApp):
    """A ``FakeApp`` whose every 2xx answer is checked against the app's response shapes."""

    def __init__(self, app: str, *, healthy: bool = True) -> None:
        super().__init__(app, healthy=healthy)
        self.violations: list[str] = []
        self.checked = 0
        LIVE.append(self)
        if healthy and rs.concrete(schema(app, "GET /api/health", 200)):
            self.on("GET", "/api/health", instance(app, "GET /api/health", 200))

    def handle(self, request: httpx.Request) -> httpx.Response:
        response = super().handle(request)
        recorded: Recorded = self.requests[-1]
        if recorded.template is not None and 200 <= response.status_code < 300:
            try:
                body = json.loads(response.content) if response.content else None
            except ValueError:
                body = response.content.decode(errors="replace")
            key = f"{recorded.method} {recorded.template}"
            self.checked += 1
            self.violations += violations(self.app, key, response.status_code, body)
        return response


def shaped_fakes(apps: tuple[str, ...]) -> dict[str, FakeApp]:
    """Core's four fakes, with ``apps`` checked against their shapes (others stay plain)."""
    from miassist.adapters.base import HEADERS

    return {a: ShapedFakeApp(a) if a in apps else FakeApp(a) for a in HEADERS}


def collected() -> list[str]:
    found = [v for fake in LIVE for v in fake.violations]
    LIVE.clear()
    return found


def part(app: str, key: str, status: int, *path: str) -> Any:
    """The sub-schema at ``path`` (``[]`` steps into a list's items)."""
    found = schema(app, key, status)
    assert found is not None, f"{app} {key} {status} has no vendored shape"
    node = rs.at(found, *path)
    if isinstance(node, dict) and "anyOf" in node and "properties" not in node:
        node = next(b for b in node["anyOf"] if rs.concrete(b) or b.get("type") == "object")
    return node


WHEN = "2026-11-16T00:00:00Z"


def _dates(shape: Any, value: Any) -> Any:
    """``example``'s placeholder string replaced by a date-time where the shape says date-time."""
    if not isinstance(shape, dict):
        return value
    for key in ("anyOf", "oneOf"):
        for branch in shape.get(key, []):
            if (
                isinstance(branch, dict)
                and branch.get("format") == "date-time"
                and value == "evalfx"
            ):
                return WHEN
    if shape.get("format") == "date-time" and value == "evalfx":
        return WHEN
    if isinstance(value, dict) and isinstance(shape.get("properties"), dict):
        return {k: _dates(shape["properties"].get(k), v) for k, v in value.items()}
    if isinstance(value, list) and isinstance(shape.get("items"), dict):
        return [_dates(shape["items"], v) for v in value]
    return value


def fill(shape: Any, /, **fields: Any) -> Any:
    """``fields`` completed with every field the app always sends; asserted valid here."""
    out = _dates(shape, rs.fill(shape, dict(fields)))
    problems = rs.check(shape, out)
    assert not problems, problems
    return out


def instance(app: str, key: str, status: int, /, **fields: Any) -> Any:
    """A valid ``status`` answer of ``key``: ``fields`` plus everything the app always sends."""
    found = schema(app, key, status)
    assert found is not None, f"{app} {key} {status} has no vendored shape"
    return fill(found, **fields)
