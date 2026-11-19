"""No registered route takes a multipart body (A14: no uploads)."""

from __future__ import annotations

import json
from pathlib import Path

from miassist.adapters.routes import ROUTES

OPENAPI = Path(__file__).resolve().parents[1] / "fixtures" / "openapi"


def test_index_holds_multipart_routes() -> None:
    multipart = [
        (app, r["method"], r["path"])
        for app in ("miworkbench", "miserver", "midataworks", "miforge")
        for r in json.loads((OPENAPI / f"{app}.index.json").read_text())["routes"]
        if any("multipart" in c for c in r["content_types"])
    ]
    assert multipart, "the index has no multipart route: this guard would be vacuous"


def test_no_registered_route_is_multipart() -> None:
    for app in ("miworkbench", "miserver", "midataworks", "miforge"):
        rows = json.loads((OPENAPI / f"{app}.index.json").read_text())["routes"]
        by_key = {(r["method"], r["path"]): r for r in rows}
        for route in ROUTES.for_app(app):
            content = by_key[(route.method, route.path)]["content_types"]
            assert not any("multipart" in c for c in content), route.id
