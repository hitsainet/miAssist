"""FR-002.12 (R1M-17): staleness against an edited REFERENCE (never an edited cassette; FTDD §10)."""

from __future__ import annotations

import copy

from miassist_eval import openapi_ref, staleness
from tests.support import harness

ROUTE = "/api/v1/publish-check-runs/{check_run_id}"


def take() -> dict:
    return harness.cassette_doc(
        [
            harness.record(
                0,
                "midataworks",
                "GET",
                "/api/v1/publish-check-runs/evalfx-cr",
                ROUTE,
                200,
                check_run(),
            ),
        ]
    )


def check_run() -> dict:
    """A CheckRunOut written by hand from the app's model (miDataworks schemas/publishing.py:58-72
    at 58087b1), not from the reference."""
    return {
        "id": "evalfx-cr",
        "version_id": "evalfx-v",
        "build_id": "evalfx-b",
        "repo_id": "evalfx-org/evalfx-refund",
        "requested_visibility": "private",
        "status": "completed",
        "results": [],
        "licence_table_version": None,
        "job_id": None,
        "created_at": "2026-11-16T09:00:00Z",
        "completed_at": "2026-11-16T09:01:00Z",
        "warnings": [],
    }


def refs_with(edit) -> dict:
    refs = harness.refs()
    raw = copy.deepcopy(refs["midataworks"].openapi)
    edit(raw)
    refs["midataworks"] = openapi_ref.build(
        "midataworks", {"openapi": raw, "fetched_on": "2026-11-16"}
    )
    return refs


def test_the_unedited_reference_accepts_the_take() -> None:
    found = staleness.check_cassette(take(), harness.refs(), {})
    assert found.stale == [], found.stale


def test_a_removed_route_is_stale_naming_it() -> None:
    refs = refs_with(lambda d: d["paths"].pop(ROUTE))
    found = staleness.check_cassette(take(), refs, {})
    assert any(ROUTE in s and "absent" in s for s in found.stale)


def test_a_changed_response_type_is_stale_with_the_json_path() -> None:
    def edit(d):
        d["components"]["schemas"]["CheckRunOut"]["properties"]["status"] = {"type": "integer"}

    found = staleness.check_cassette(take(), refs_with(edit), {})
    assert any("answer.status" in s for s in found.stale), found.stale


def test_a_newly_required_request_field_is_stale_with_its_path() -> None:
    def edit(d):
        op = d["paths"][ROUTE]["get"]
        op.setdefault("parameters", []).append(
            {"name": "include_rows", "in": "query", "required": True, "schema": {"type": "boolean"}}
        )

    found = staleness.check_cassette(take(), refs_with(edit), {})
    assert any("request.query.include_rows" in s for s in found.stale), found.stale


def test_a_new_required_body_field_is_stale() -> None:
    rec = harness.record(
        0,
        "midataworks",
        "POST",
        "/api/v1/versions/evalfx-v/publish-checks",
        "/api/v1/versions/{version_id}/publish-checks",
        202,
        {"check_run_id": "evalfx-cr", "job_id": "evalfx-j", "status": "queued"},
        req_body={},
    )

    def edit(d):
        op = d["paths"]["/api/v1/versions/{version_id}/publish-checks"]["post"]
        op["requestBody"] = {
            "required": True,
            "content": {
                "application/json": {
                    "schema": {
                        "type": "object",
                        "required": ["repo_id"],
                        "properties": {"repo_id": {"type": "string"}},
                    }
                }
            },
        }

    found = staleness.check_cassette(harness.cassette_doc([rec]), refs_with(edit), {})
    assert any("request.body" in s and "repo_id" in s for s in found.stale), found.stale


def test_a_different_hash_with_everything_valid_is_compatible_drift() -> None:
    found = staleness.check_cassette(take(), harness.refs(), {"midataworks": "0" * 64})
    assert found.stale == [] and found.drift == {"midataworks": "compatible"}
