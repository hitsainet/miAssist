"""FR-002.14c: list answers are filtered before the server under test or the take sees them."""

from __future__ import annotations

import pytest

from miassist_eval import allowed, classes
from miassist_eval.recorder import Recorder
from tests.support import harness

H = harness.HEADERS["midataworks"]


def recorder(answer, writing: bool = True) -> tuple[Recorder, list]:
    seen = []

    async def forward(app, method, path, query, headers, body):
        seen.append(path)
        return 200, {}, answer

    return (
        Recorder(
            edge=harness.edge(),
            forward=forward,
            allowed_set=allowed.AllowedSet(),
            app_versions={},
            writing=writing,
        ),
        seen,
    )


async def test_a_mixed_list_reaches_the_server_and_the_take_filtered() -> None:
    answer = {
        "items": [
            {"id": "evalfx-ds-1", "name": "evalfx-refund-messages"},
            {"id": "ds-operator-9", "name": "customer-pii"},
        ],
        "total": 2,
    }
    rec, _ = recorder(answer)
    status, _, body = await rec.handle("midataworks", "GET", "/api/v1/datasets", {}, H, None)
    assert status == 200
    assert body["items"] == [{"id": "evalfx-ds-1", "name": "evalfx-refund-messages"}]
    assert body["total"] == 1
    assert rec.records[0]["answer"]["body"] == body, "the take differs from what the server saw"
    assert "customer-pii" not in str(rec.records)


async def test_approval_lists_keep_the_runs_own() -> None:
    answer = {
        "approvals": [
            {"id": "ap-run-1", "status": "pending"},
            {"id": "ap-operator-2", "status": "pending"},
        ]
    }
    rec, _ = recorder(answer)
    rec.allowed_set.created.add("ap-run-1")
    _, _, body = await rec.handle("midataworks", "GET", "/api/v1/approvals", {}, H, None)
    assert [a["id"] for a in body["approvals"]] == ["ap-run-1"]


async def test_hf_search_keeps_only_public_ungated_allowed_items() -> None:
    answer = [
        {"id": "Salesforce/wikitext", "private": False, "gated": False},
        {"id": "Salesforce/wikitext-gated", "private": False, "gated": True},
        {"id": "someone/other", "private": False, "gated": False},
    ]
    rec, _ = recorder(answer)
    rec.allowed_set.repositories.update({"Salesforce/wikitext", "Salesforce/wikitext-gated"})
    _, _, body = await rec.handle(
        "midataworks", "POST", "/api/v1/sources/hf/search", {}, H, {"query": "wikitext"}
    )
    assert body == [{"id": "Salesforce/wikitext", "private": False, "gated": False}]


async def test_an_uncovered_route_with_an_object_array_is_refused() -> None:
    answer = {"rows": [{"id": "x"}]}
    rec, _ = recorder(answer)
    status, _, body = await rec.handle(
        "midataworks", "POST", "/api/v1/versions/evalfx-v/leakage", {}, H, {}
    )
    assert status == 502 and body["refused"] == classes.UNFILTERED_LIST
    assert rec.records == [] and rec.failures[0][0] == classes.UNFILTERED_LIST


@pytest.mark.parametrize(
    "body", [{"items": [{"id": "x"}]}, [{"id": "x"}], {"data": {"rows": [{"id": "x"}]}}]
)
def test_object_arrays_are_found(body) -> None:
    assert allowed.has_object_array(body)


def test_scalars_and_scalar_lists_are_not_lists() -> None:
    assert not allowed.has_object_array({"ids": ["a", "b"], "n": 1})
