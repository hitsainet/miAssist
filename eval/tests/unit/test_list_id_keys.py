"""A route profile's list ``items`` and ``id`` are what the answer carries (FU-10, 2026-11-25).

Before FU-10 every generated list entry said ``id: id``: miForge's WSP candidates are keyed
``candidate_id``, its runs ``run_id``, and a held-out use has no single id. Each claim is checked here
against the answer's schema, never against a list in this file: the reference OpenAPI's 2xx schema,
or, where that is an open ``dict``, Core's vendored shape (``tests/fixtures/openapi/responses.json``,
each entry citing the app's code; ``openapi_ref.vendored_shape``).
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest
import yaml

from miassist_eval import allowed, openapi_ref

EVAL_ROOT = Path(__file__).resolve().parents[2]


def profile(app: str) -> dict[str, Any]:
    data: dict[str, Any] = yaml.safe_load(
        (EVAL_ROOT / "route_profiles" / f"{app}.yaml").read_text()
    )
    return data


def reference_answer(doc: Any, method: str, template: str) -> Any:
    route = doc.route(method, template)
    assert route is not None, f"{method} {template} is not in {doc.app}'s reference"
    for status, entry in route.op.get("responses", {}).items():
        if status.startswith("2"):
            return ((entry.get("content") or {}).get("application/json") or {}).get("schema")
    return None


def items_of(
    app: str, doc: Any, method: str, template: str
) -> tuple[str, Mapping[str, Any]] | None:
    """Where the answer's items are and one item's schema: the vendored answer contract's (ENH-013
    006), else the reference's, else Core's hand shape."""
    found = allowed.object_array(openapi_ref.contract_shape(app, method, template), {})
    if found is not None:
        return found
    comps = doc.openapi.get("components", {}).get("schemas", {})
    found = allowed.object_array(reference_answer(doc, method, template), comps)
    if found is None:
        found = allowed.object_array(openapi_ref.vendored_shape(app, method, template), {})
    return found


@pytest.mark.parametrize("app", openapi_ref.APPS)
def test_a_claimed_id_is_a_field_the_items_carry(app: str) -> None:
    doc = openapi_ref.load(app)
    claimed = 0
    for entry in profile(app)["routes"]:
        spec = entry.get("list")
        if not isinstance(spec, Mapping):
            continue
        where = f"{app} {entry['method']} {entry['route']}"
        found = items_of(app, doc, entry["method"], entry["route"])
        if found is not None:
            assert spec["items"] == (found[0] or "*"), f"{where}: the items are at {found[0]!r}"
        if "id" not in spec:
            continue
        claimed += 1
        assert found is not None, f"{where} claims id {spec['id']!r}, but no schema types its items"
        fields = allowed.item_fields(found[1])
        assert (
            spec["id"] in fields
        ), f"{where}: its items carry no {spec['id']!r} ({sorted(fields)})"
    assert claimed, f"{app}'s profile claims no id at all: the check would pass vacuously"


@pytest.mark.parametrize("app", openapi_ref.APPS)
def test_an_item_with_an_id_field_is_claimed_by_it(app: str) -> None:
    """The other direction: a profile that drops every ``id`` would pass the test above."""
    doc = openapi_ref.load(app)
    for entry in profile(app)["routes"]:
        spec = entry.get("list")
        if not isinstance(spec, Mapping):
            continue
        found = items_of(app, doc, entry["method"], entry["route"])
        if found is not None and "id" in allowed.item_fields(found[1]):
            assert spec.get("id") == "id", f"{app} {entry['method']} {entry['route']}"


def test_miforge_wsp_lists_are_read_from_the_vendored_shapes() -> None:
    """miForge's WSP lists answer a ``dict`` (no response model), so only Core's vendored shape
    names their items; each list is keyed as the shape says, ``candidates`` by the field its own
    item read is named for (``GET /api/v1/wsp/candidates/{candidate_id}``)."""
    doc = openapi_ref.load("miforge")
    comps = doc.openapi.get("components", {}).get("schemas", {})
    wsp = [
        e
        for e in profile("miforge")["routes"]
        if e["method"] == "GET" and e["route"].startswith("/api/v1/wsp/") and "{" not in e["route"]
    ]
    assert len(wsp) >= 7, [e["route"] for e in wsp]
    for entry in wsp:
        assert (
            allowed.object_array(reference_answer(doc, "GET", entry["route"]), comps) is None
        ), f"{entry['route']}: the reference now types the answer; the vendored shape is not needed"
        shape = openapi_ref.vendored_shape("miforge", "GET", entry["route"])
        assert shape is not None, f"{entry['route']}: no vendored shape (scripts.snapshot_shapes)"
        found = allowed.object_array(shape, {})
        assert found is not None and entry["list"]["items"] == found[0], entry
    candidates = next(e for e in wsp if e["route"] == "/api/v1/wsp/candidates")
    prefix = "/api/v1/wsp/candidates/{"
    item_reads = [
        r.template[len(prefix) : -1]
        for r in doc.routes
        if r.method == "GET"
        and r.template.startswith(prefix)
        and "/" not in r.template[len(prefix) :]
    ]
    assert len(item_reads) == 1, item_reads
    shape = openapi_ref.vendored_shape("miforge", "GET", "/api/v1/wsp/candidates")
    found = allowed.object_array(shape, {})
    assert found is not None and item_reads[0] in allowed.item_fields(found[1])
    assert candidates["list"].get("id") == item_reads[0]
