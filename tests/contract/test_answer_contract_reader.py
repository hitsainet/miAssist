"""The answer-contract reader on a synthetic contract (ENH-013 006, FTASKS 1.5; FR-006.4, FR-006.5).

No sibling contract is vendored before 006-1, so the reader is proven here against
``tests/support/synthetic_contract.py`` (miServer's layout, cut down from its contract). The
delegation cases install that contract as miServer's and set miServer ``vendored`` for one test,
then read through ``response_shapes.schema_for``, the function every fake's check goes through:
- M6 (the reader falls back to the snapshot for a ``vendored`` app) turns them red;
- M7 (objects not closed) turns the invented-key case red;
- M8 (``required`` widened to every property) turns the optional-field case red.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

from tests.support import answer_contracts as ac
from tests.support import response_shapes as rs
from tests.support import shapes
from tests.support import synthetic_contract as sc


@pytest.fixture
def contract() -> ac.Contract:
    return ac.Contract(sc.APP, sc.document())


@pytest.fixture
def miserver_vendored(monkeypatch: pytest.MonkeyPatch, contract: ac.Contract) -> ac.Contract:
    """miServer read from the synthetic contract, for this test only."""
    monkeypatch.setitem(ac.LOADED, "miserver", contract)
    monkeypatch.setitem(ac.ANSWER_SOURCES, "miserver", "vendored")
    return contract


def refs(node: Any) -> list[str]:
    if isinstance(node, dict):
        return [str(v) for k, v in node.items() if k == "$ref"] + [
            r for k, v in node.items() if k != "$defs" for r in refs(v)
        ]
    if isinstance(node, list):
        return [r for v in node for r in refs(v)]
    return []


STATUS: dict[str, Any] = {
    "success": True,
    "data": {"armed": 2, "served_weights": "base"},
    "error": None,
}
SUMMARY: dict[str, Any] = {"id": "p1", "name": "refund", "derived_from": None}


# -- reading -----------------------------------------------------------------------------------


def test_a_route_reads_with_every_reference_resolved(contract: ac.Contract) -> None:
    """FR-006.4 AC: the status answer comes back whole, with no ``$ref`` left."""
    found = contract.resolved("GET", "/api/probes/status", 200)
    assert refs(found) == []
    data = found["properties"]["data"]["anyOf"][0]
    assert data["properties"]["served_weights"]["enum"] == ["base", "attached"]
    assert data["description"] == "The status", "a $ref's siblings are kept over its target"


def test_an_excluded_route_and_an_absent_answer_have_no_shape(contract: ac.Contract) -> None:
    """FR-006.4 AC: a route that answers no JSON has no shape, so a JSON fake for it fails."""
    assert contract.entry("GET", "/api/health/metrics/prometheus", 200) is None
    assert contract.resolved("GET", "/api/probes/status", 404) is None
    assert contract.resolved("GET", "/api/nowhere", 200) is None
    assert contract.statuses("POST", "/v1/chat/completions") == ["200"]
    assert contract.entry("POST", "/v1/chat/completions", "x-variants") is None


def test_an_excluded_route_has_no_shape_even_with_a_responses_entry() -> None:
    """``excluded`` wins over ``responses``: a route the producer says answers no JSON has no shape
    even if an entry for it is present too. miServer's contract keeps the two disjoint by
    construction, which is why removing the check survived the suite (006-1 review, D7)."""
    route = "GET /api/health/metrics/prometheus"
    doc = sc.document(responses={**sc.RESPONSES, route: {"200": {"type": "object"}}})
    both = ac.Contract(sc.APP, doc)
    assert both.entry("GET", "/api/health/metrics/prometheus", 200) is None
    assert both.schema_for("GET", "/api/health/metrics/prometheus", 200) is None
    assert both.resolved("GET", "/api/health/metrics/prometheus", 200) is None


def test_a_union_keeps_its_branches(contract: ac.Contract) -> None:
    found = contract.resolved("GET", "/api/probes", 200)
    branches = found["properties"]["data"]["anyOf"]
    assert [b.get("type") for b in branches] == ["array", "null"]


def test_an_external_reference_is_an_open_object(contract: ac.Contract) -> None:
    """AT3: an ``external`` ``$id`` is read as an open object, and the contract lists which."""
    assert list(contract.external) == [sc.EXTERNAL]
    found = contract.resolved("GET", "/api/clusters/{cluster_id}", 200)
    assert found["properties"]["definition"] == {"type": "object"}
    assert rs.check(found, {"id": "c1", "definition": {"anything": [1]}}) == []
    assert rs.check(found, {"id": "c1", "definition": "x"}) != []


def test_a_definition_that_refers_to_itself_is_carried_not_unrolled(contract: ac.Contract) -> None:
    found = contract.resolved("GET", "/api/tree", 200)
    assert set(found["$defs"]) == {"Node"}
    tree = {"name": "a", "children": [{"name": "b", "children": [{"name": "c", "children": []}]}]}
    assert rs.check(found, tree) == []
    bad = {"name": "a", "children": [{"name": "b", "children": [{"name": 3, "children": []}]}]}
    assert rs.check(found, bad) == [
        "$.children[0].children[0].name: int where the app sends ['string']"
    ]


def test_a_route_key_is_escaped_as_a_json_pointer(contract: ac.Contract) -> None:
    """RFC 6901: ``~`` is ``~0`` and ``/`` is ``~1`` inside the ``$ref`` form."""
    ref = contract.schema_for("GET", "/api/a~b/{c}", 200)
    assert ref == {"$ref": f"{sc.ID}#/responses/GET ~1api~1a~0b~1{{c}}/200"}
    good = {"code": "x", "message": "y"}
    assert rs.check(ref, good, resources=contract.resources()) == []
    assert rs.check(ref, {**good, "z": 1}, resources=contract.resources()) == [
        "$.z: invented (the app never sends it)"
    ]


@pytest.mark.parametrize(
    ("method", "template", "status", "value"),
    [
        ("GET", "/api/probes/status", 200, STATUS),
        ("GET", "/api/probes/status", 200, {**STATUS, "data": {"armed": "2"}}),
        ("POST", "/api/probes/import", 201, {**SUMMARY, "results_total": 1}),
        (
            "GET",
            "/api/probes",
            200,
            {"success": True, "data": [SUMMARY], "error": None, "meta": {}},
        ),
        ("GET", "/api/tree", 200, {"name": "a", "children": [{"name": 1, "children": []}]}),
        ("GET", "/api/approvals/{approval_id}", 200, {"approval_id": "x"}),
        # an external ``$id`` resolves through ``resources()`` as an open object (AT3; 006-1
        # review, D10: dropping it from the registry survived, as no case reached one)
        ("GET", "/api/clusters/{cluster_id}", 200, {"id": "c1", "definition": {"any": [1]}}),
        ("GET", "/api/clusters/{cluster_id}", 200, {"id": "c1", "definition": "x"}),
    ],
)
def test_the_ref_form_and_the_inlined_form_agree(
    miserver_vendored: ac.Contract, method: str, template: str, status: int, value: Any
) -> None:
    """The ``$ref`` form, through the contract's registry, and the inlined form give one verdict."""
    inlined = rs.check(miserver_vendored.resolved(method, template, status), value)
    assert ac.check("miserver", method, template, status, value) == inlined


# -- the strict form, through the wiring the fakes use (response_shapes.schema_for) ----------------


def test_a_vendored_app_reads_its_contract_and_nothing_else(
    miserver_vendored: ac.Contract, monkeypatch: pytest.MonkeyPatch
) -> None:
    """M6's case: a ``vendored`` app's shape is the contract's, even where ``responses.json`` held a
    hand entry for the route (a planted one; 006-1 deleted miServer's)."""
    hand = {"commit": "x", "routes": {"GET /api/probes/status": {"200": {"schema": {}}}}}
    monkeypatch.setitem(rs.vendored()["apps"], "miserver", hand)
    for method, template, status in (
        ("GET", "/api/probes/status", 200),
        ("POST", "/api/probes/import", 201),
    ):
        assert rs.shape_source("miserver", method, template, status) == "contract"
        assert rs.schema_for("miserver", method, template, status) == ac.strict_form(
            miserver_vendored.inlined(method, template, status)
        )
    assert rs.shape_source("miserver", "GET", "/api/probes/status", 201) == "contract"
    assert rs.schema_for("miserver", "GET", "/api/probes/status", 201) is None
    assert rs.shape_source("miserver", "GET", "/api/probes/status", 404) == "contract"
    assert rs.schema_for("miserver", "GET", "/api/probes/status", 404) == (
        miserver_vendored.error_schema("management")
    ), "a refusal is the contract's error envelope (FR-006.7)"


def test_a_hand_app_reads_its_hand_records() -> None:
    assert not ac.vendored("midataworks")
    assert rs.shape_source("midataworks", "GET", "/api/v1/approvals", 200) == "responses.json"


def test_an_invented_key_is_refused(miserver_vendored: ac.Contract) -> None:
    """FR-006.5 AC: ``results_total`` belongs only to ``ProbeListItem``, the list's model."""
    shape = rs.schema_for("miserver", "POST", "/api/probes/import", 201)
    assert (
        shape is not None and shape["additionalProperties"] is False
    ), "the shape a fake is built from is closed"
    assert "additionalProperties" not in miserver_vendored.defs["ProbeSummary"]
    assert rs.check(shape, SUMMARY) == []
    assert rs.check(shape, {**SUMMARY, "results_total": 3}) == [
        "$.results_total: invented (the app never sends it)"
    ]


def test_a_dropped_required_key_is_refused(miserver_vendored: ac.Contract) -> None:
    """FR-006.5 AC: a list item without ``results_total`` is "dropped"."""
    shape = rs.schema_for("miserver", "GET", "/api/probes", 200)
    page = {"success": True, "data": [SUMMARY], "error": None, "meta": None}
    assert rs.check(shape, page) == [
        "$.data: matches no branch ($.data[0].results_total: dropped (the app always sends it))"
    ]
    page["data"] = [{**SUMMARY, "results_total": 0}]
    assert rs.check(shape, page) == []


def test_a_field_the_contract_leaves_optional_may_be_omitted(
    miserver_vendored: ac.Contract,
) -> None:
    """FR-006.5 AC (M8's case): ``system_fingerprint`` is not in ``required``, so omitting it
    passes; ``required`` is the contract's own, never every property."""
    shape = rs.schema_for("miserver", "POST", "/v1/chat/completions", 200)
    assert rs.check(shape, {"id": "c1", "object": "chat.completion"}) == []
    assert rs.check(shape, {"object": "chat.completion"}) == [
        "$.id: dropped (the app always sends it)"
    ]


def test_a_map_takes_any_key(miserver_vendored: ac.Contract) -> None:
    """FR-006.5 AC: a new key inside an approval's ``summary`` map passes."""
    shape = rs.schema_for("miserver", "GET", "/api/approvals/{approval_id}", 200)
    answer = {"approval_id": "apr_1", "action": "x", "summary": {"new": 1}, "result": None}
    assert rs.check(shape, answer) == []
    assert rs.check(shape, {**answer, "extra": 1}) == ["$.extra: invented (the app never sends it)"]


def test_a_history_form_result_keeps_no_required(miserver_vendored: ac.Contract) -> None:
    """FR-006.5: an old approval's stored ``result`` may lack fields its model has since gained;
    the history form still refuses an invented one and a wrong type."""
    shape = rs.schema_for("miserver", "GET", "/api/approvals/{approval_id}", 200)
    answer = {"approval_id": "apr_1", "action": "capacity_measure", "summary": {}}
    assert rs.check(shape, {**answer, "result": {}}) == []
    assert rs.check(shape, {**answer, "result": {"armed": 1, "cards": []}}) == []
    assert rs.check(shape, {**answer, "result": {"armed": "x"}}) != []
    assert rs.check(shape, {**answer, "result": {"made_up": 1}}) != []
    plain = miserver_vendored.defs["ProbeCapacity__history"]
    assert plain["required"] == ["armed", "cards"], "the copy itself is never changed"


def test_a_fake_built_from_a_contract_shape_passes_its_own_check(
    miserver_vendored: ac.Contract,
) -> None:
    """``shapes.instance`` builds a fake answer from the contract (``example`` and ``fill``), and
    ``shapes.violations``, the teardown check, passes it and names what an invention breaks."""
    built = shapes.instance("miserver", "GET /api/probes/status", 200, success=True)
    assert shapes.violations("miserver", "GET /api/probes/status", 200, built) == []
    found = shapes.violations("miserver", "GET /api/probes/status", 200, {**built, "made_up": 1})
    assert found == [
        "miserver GET /api/probes/status 200 $.made_up: invented (the app never sends it)"
    ]
    assert shapes.violations("miserver", "GET /api/health/metrics/prometheus", 200, {}) == [
        "miserver GET /api/health/metrics/prometheus 200: no vendored shape (the fake would be "
        "inventing it)"
    ]


def test_the_error_envelope_is_read_strict(contract: ac.Contract) -> None:
    envelope = contract.error_schema("management")
    good = {"success": False, "data": None, "error": {"code": "NOT_FOUND", "message": "m"}}
    assert rs.check(envelope, good) == []
    assert rs.check(envelope, {**good, "detail": "x"}) == [
        "$.detail: invented (the app never sends it)"
    ]
    with pytest.raises(KeyError, match="no 'app' error envelope"):
        contract.error_schema("app")


# -- loading -------------------------------------------------------------------------------------


def test_a_copy_loads_with_its_kind_and_digest_checked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A damaged copy fails in ``load``, naming the digest, not later as a vague shape error."""
    monkeypatch.setenv("MIASSIST_ANSWER_CONTRACTS_DIR", str(tmp_path))
    doc = sc.document()
    (tmp_path / ac.FILES["miserver"]).write_text(sc.render(doc))
    assert ac.load("miserver") == doc
    edited = json.loads(sc.render(doc))
    edited["$defs"]["ProbeStatus"]["required"] = ["armed"]
    (tmp_path / ac.FILES["miserver"]).write_text(sc.render(edited))
    with pytest.raises(ac.ContractError, match="content_sha256"):
        ac.load("miserver")
    (tmp_path / ac.FILES["miserver"]).write_text(sc.render(sc.document("midataworks")))
    with pytest.raises(ac.ContractError, match=re.escape("expected 'miserver.answer-contract/v1'")):
        ac.load("miserver")
    (tmp_path / ac.FILES["miserver"]).unlink()
    with pytest.raises(ac.ContractError, match="does not exist"):
        ac.load("miserver")


def test_the_digest_is_the_producers_rule() -> None:
    """``content_sha256`` covers everything but itself and ``revision`` (miServer FR-044.18)."""
    doc = sc.document()
    assert ac.content_digest(doc) == doc["content_sha256"]
    assert ac.content_digest({**doc, "revision": 7}) == doc["content_sha256"]
    assert ac.content_digest({**doc, "title": "x"}) != doc["content_sha256"]
