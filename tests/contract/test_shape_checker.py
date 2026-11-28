"""The answer-shape checker reads every rule of a shape (2026-11-25 fix; ENH-013 FR-006.5).

Before this fix ``tests/support/response_shapes.check`` was a hand-written walk over
``properties``, ``items``, ``anyOf``/``oneOf``, ``enum``, ``const`` and ``type``. It followed no
``$ref`` and ignored ``if``/``then``, ``allOf``, ``prefixItems``, bounds and patterns, so an answer
wrong at any of them passed, and every fake built on it could be wrong there. miServer's answer
contract (``docs/schemas/miserver-answers-v1.json`` on miServer's ``feat/044-typed-answers`` at
``a8ff9281``) uses all four, so it would have checked nothing below its first ``$ref``.

Each wrong answer below passed the old walk (``check`` returned ``[]``) and fails now. The first
three are wrong at today's own vendored shapes; the rest are cut down from that contract's
``$defs`` (``ApprovalRead``'s ``if``/``then`` history forms, ``ProbeSummary`` against
``ProbeListItem``). The strict form keeps today's closing and required-ness: an object with
``properties`` is closed unless its ``additionalProperties`` is a schema or ``true``, and
``required`` is the shape's own.
"""

from __future__ import annotations

from typing import Any

import pytest

from tests.support import response_shapes as rs

# -- wrong at today's vendored shapes ---------------------------------------------------------


def test_a_cluster_member_tuple_of_the_wrong_types_is_refused() -> None:
    """``prefixItems``: miServer's ``ClusterSummary.members`` is ``[int, str | null, float]``."""
    shape = rs.schema_for("miserver", "GET", "/api/clusters", 200)
    cluster = rs.at(shape, "data", "clusters", "[]")
    good = rs.fill(cluster, {"members": [[7, "refund", 0.5]]})
    assert rs.check(cluster, good) == []
    wrong = {**good, "members": [["refund", 7, "high"]]}
    assert rs.check(cluster, wrong) == [
        "$.members[0][0]: str where the app sends ['integer']",
        "$.members[0][1]: matches no branch ($.members[0][1]: int where the app sends ['string'])",
        "$.members[0][2]: str where the app sends ['number']",
    ]


def test_an_approval_id_outside_the_apps_pattern_is_refused() -> None:
    """``pattern``: miDataworks' approval ids start ``apr_``; the detector fake sent
    ``dw_ap_evalfx-1`` for its whole life, and nothing noticed."""
    shape = rs.schema_for("midataworks", "POST", "/api/v1/detector-sets/send", 202)
    approval = {"id": "apr_evalfx-1", "status": "pending", "summary": "hub_push"}
    good = rs.fill(
        shape,
        {
            "approval_id": "apr_evalfx-1",
            "request_digest": "sha256:" + "0" * 64,
            "approval": approval,
        },
    )
    assert rs.check(shape, good) == []
    found = rs.check(shape, {**good, "approval_id": "dw_ap_evalfx-1"})
    assert found == ["$.approval_id: 'dw_ap_evalfx-1' does not match '^apr_'"]


def test_a_journey_of_the_wrong_length_is_refused() -> None:
    """``minItems``/``maxItems``: miDataworks always sends its thirteen journey steps."""
    shape = rs.schema_for("midataworks", "GET", "/api/v1/behaviours/{key}/status", 200)
    journey = rs.at(shape, "journey")
    assert journey["minItems"] == journey["maxItems"] == 13
    step = rs.example(journey["items"])
    assert rs.check(journey, [step] * 13) == []
    (found,) = rs.check(journey, [step])
    assert found.startswith("$: [") and found.endswith("is too short") and len(found) < 200


# -- the contract's forms: $ref, if/then, allOf -------------------------------------------------

SUMMARY: dict[str, Any] = {
    "properties": {"id": {"type": "string"}, "derived_from": {"type": ["string", "null"]}},
    "required": ["id", "derived_from"],
    "type": "object",
}
CONTRACT: dict[str, Any] = {
    "$defs": {
        "ProbeSummary": SUMMARY,
        "ProbeListItem": {
            "properties": {**SUMMARY["properties"], "results_total": {"type": "integer"}},
            "required": [*SUMMARY["required"], "results_total"],
            "type": "object",
        },
        "ProbeCapacity__history": {
            "properties": {"armed": {"type": "integer"}, "cards": {"type": "array"}},
            "type": "object",
        },
        "ApprovalRead": {
            "properties": {
                "approval_id": {"type": "string"},
                "action": {"type": "string"},
                "summary": {"additionalProperties": True, "type": "object"},
                "result": {},
            },
            "required": ["action", "summary", "result"],
            "type": "object",
            "allOf": [
                {
                    "if": {
                        "properties": {"action": {"const": "capacity_measure"}},
                        "required": ["action"],
                    },
                    "then": {
                        "properties": {
                            "result": {
                                "anyOf": [
                                    {"$ref": "#/$defs/ProbeCapacity__history"},
                                    {"type": "null"},
                                ]
                            }
                        }
                    },
                },
                {"required": ["approval_id"]},
            ],
        },
    },
    "responses": {
        "POST /api/probes/import": {"201": {"$ref": "#/$defs/ProbeSummary"}},
        "GET /api/probes": {"200": {"items": {"$ref": "#/$defs/ProbeListItem"}, "type": "array"}},
        "GET /api/approvals/{approval_id}": {"200": {"$ref": "#/$defs/ApprovalRead"}},
    },
}


def answer(route: str, status: str = "200") -> Any:
    """The answer schema of ``route``: a part of ``CONTRACT``, checked with the whole as root."""
    return CONTRACT["responses"][route][status]


def test_a_summary_carrying_a_list_field_is_invented_through_its_ref() -> None:
    """FR-006.5's first case: ``results_total`` belongs only to ``ProbeListItem``."""
    part = answer("POST /api/probes/import", "201")
    good = {"id": "p1", "derived_from": None}
    assert rs.check(part, good, root=CONTRACT) == []
    assert rs.check(part, {**good, "results_total": 3}, root=CONTRACT) == [
        "$.results_total: invented (the app never sends it)"
    ]


def test_a_list_item_without_its_list_field_is_dropped_through_its_ref() -> None:
    part = answer("GET /api/probes")
    item = {"id": "p1", "derived_from": None}
    assert rs.check(part, [{**item, "results_total": 3}], root=CONTRACT) == []
    assert rs.check(part, [item], root=CONTRACT) == [
        "$[0].results_total: dropped (the app always sends it)"
    ]


APPROVAL = {"approval_id": "apr_1", "action": "capacity_measure", "summary": {}, "result": None}


def test_an_approval_result_is_checked_in_the_form_its_action_names() -> None:
    """``if``/``then``: a ``capacity_measure`` approval's ``result`` is a capacity."""
    part = answer("GET /api/approvals/{approval_id}")
    good = {**APPROVAL, "result": {"armed": 2, "cards": []}}
    assert rs.check(part, good, root=CONTRACT) == []
    assert rs.check(part, {**good, "result": {"armed": "two"}}, root=CONTRACT) == [
        "$.result: matches no branch ($.result.armed: str where the app sends ['integer'])"
    ]
    assert rs.check(part, {**good, "result": {"made_up": 1}}, root=CONTRACT)[0].startswith(
        "$.result: matches no branch ($.result.made_up: invented"
    )
    # another action leaves ``result`` as the base model says (unconstrained here)
    assert rs.check(part, {**good, "action": "model_load", "result": {"x": 1}}, root=CONTRACT) == []


def test_the_partial_subschemas_are_not_closed() -> None:
    """An ``if`` names only ``action`` and a ``then`` only ``result``: closing either would refuse
    every real approval (the ``if`` would never match, so its ``then`` would never apply)."""
    part = answer("GET /api/approvals/{approval_id}")
    assert rs.check(part, APPROVAL, root=CONTRACT) == []
    assert rs.check(part, {**APPROVAL, "result": {"armed": "x"}}, root=CONTRACT) != []


def test_an_all_of_rule_is_read() -> None:
    part = answer("GET /api/approvals/{approval_id}")
    missing = {k: v for k, v in APPROVAL.items() if k != "approval_id"}
    assert rs.check(part, missing, root=CONTRACT) == [
        "$.approval_id: dropped (the app always sends it)"
    ]


def test_a_new_key_in_an_open_map_passes() -> None:
    """FR-006.5: an object whose ``additionalProperties`` is a schema or ``true`` stays open."""
    part = answer("GET /api/approvals/{approval_id}")
    assert rs.check(part, {**APPROVAL, "summary": {"anything": 1}}, root=CONTRACT) == []


def test_a_ref_that_does_not_resolve_is_reported_not_passed() -> None:
    found = rs.check({"$ref": "#/$defs/Missing"}, {"x": 1})
    assert len(found) == 1 and "does not resolve" in found[0]


def test_an_external_document_resolves_through_resources() -> None:
    uri = "https://example.invalid/schemas/thing-v1.json"
    shape = {"properties": {"thing": {"$ref": uri}}, "required": ["thing"]}
    thing = {"properties": {"n": {"type": "integer"}}, "required": ["n"]}
    assert rs.check(shape, {"thing": {"n": 1}}, resources={uri: thing}) == []
    assert rs.check(shape, {"thing": {"n": 1, "m": 2}}, resources={uri: thing}) == [
        "$.thing.m: invented (the app never sends it)"
    ]


# -- today's semantics, kept --------------------------------------------------------------------


def test_an_object_with_properties_is_closed_without_saying_so() -> None:
    """A hand-derived entry rarely writes ``additionalProperties``; it has always been closed."""
    shape = {"properties": {"a": {"type": "string"}}, "required": ["a"]}
    assert rs.check(shape, {"a": "x", "b": 1}) == ["$.b: invented (the app never sends it)"]
    assert rs.check({"type": "object"}, {"b": 1}) == []


def test_required_is_never_widened() -> None:
    """FR-006.5: a field the shape leaves out of ``required`` may be absent."""
    shape = {"properties": {"a": {"type": "string"}, "b": {"type": "string"}}, "required": ["a"]}
    assert rs.check(shape, {"a": "x"}) == []


def test_an_object_that_says_it_is_open_stays_open() -> None:
    """An object with ``properties`` AND ``additionalProperties: true`` (three in miServer's
    contract) or a schema keeps what it says; only an unsaid one is closed."""
    named = {"a": {"type": "string"}}
    assert rs.check({"properties": named, "additionalProperties": True}, {"a": "x", "b": 1}) == []
    typed = {"properties": named, "additionalProperties": {"type": "integer"}}
    assert rs.check(typed, {"a": "x", "b": 1}) == []
    assert rs.check(typed, {"a": "x", "b": "y"}) == ["$.b: str where the app sends ['integer']"]


def test_a_map_checks_its_values() -> None:
    shape = {"type": "object", "additionalProperties": {"type": "integer"}}
    assert rs.check(shape, {"x": 1, "y": "2"}) == ["$.y: str where the app sends ['integer']"]


@pytest.mark.parametrize("value", [1.0, True])
def test_an_integer_is_an_int(value: Any) -> None:
    assert rs.check({"type": "integer"}, value) == [
        f"$: {type(value).__name__} where the app sends ['integer']"
    ]


def test_one_of_matching_two_branches_is_refused() -> None:
    shape = {"oneOf": [{"type": "integer"}, {"type": "number"}]}
    assert rs.check(shape, 1.5) == []
    assert rs.check(shape, 1) == ["$: matches more than one branch (the app sends one)"]


def test_a_wrong_type_is_the_only_report_at_its_place() -> None:
    """As before: a value of the wrong type is not also reported against the type's bounds."""
    shape = {"properties": {"n": {"type": "string", "enum": ["a"], "minLength": 3}}}
    assert rs.check(shape, {"n": 5}) == ["$.n: 5 is not one of ['a']"]
