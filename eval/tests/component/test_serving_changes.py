"""FR-002.11c: serving changes are the operator's on both surfaces; the held state flips only after
the "done" reply."""

from __future__ import annotations

import pytest

from miassist_eval import classes, replay
from miassist_eval.edge import SERVING_CHANGES
from tests.support import harness

#: Written here (FR-002.11c's list), independent of SERVING_CHANGES.
FPRD = [
    ("POST", "/api/probes/{probe_id}/arm"),
    ("POST", "/api/probes/{probe_id}/disarm"),
    ("POST", "/api/probes/behaviours/{key}/arm"),
    ("POST", "/api/probes/behaviours/{key}/disarm"),
    ("POST", "/api/clusters/{cluster_id}/activate"),
    ("POST", "/api/clusters/{cluster_id}/deactivate"),
    ("PUT", "/api/clusters/active/intensity"),
    ("PUT", "/api/clusters/{cluster_id}/intensity"),
    ("POST", "/api/circuits/{circuit_id}/activate"),
    ("POST", "/api/circuits/{circuit_id}/deactivate"),
    ("PUT", "/api/circuits/active/intensity"),
]


def concrete(template: str) -> str:
    return (
        template.replace("{probe_id}", "evalfx-p")
        .replace("{key}", "evalfx-k")
        .replace("{cluster_id}", "evalfx-c")
        .replace("{circuit_id}", "evalfx-ci")
    )


@pytest.mark.parametrize(("method", "template"), FPRD)
@pytest.mark.parametrize(
    ("surface", "cls"),
    [("miassist", classes.FORBIDDEN_ROUTE), ("baseline", classes.OPERATOR_HANDOFF)],
)
def test_each_route_is_refused_per_surface(
    method: str, template: str, surface: str, cls: str
) -> None:
    assert (method, template) in SERVING_CHANGES
    edge = harness.edge(surface)
    route, verdict = edge.check(
        "miserver", method, concrete(template), {}, harness.HEADERS["miserver"], {}
    )
    assert (
        route is not None and verdict is not None and verdict.cls == cls and verdict.status == 403
    )
    if surface == "baseline":
        assert verdict.body["message"] == "The operator does this in miServer."


@pytest.mark.parametrize("where", ["query", "body"])
def test_an_import_with_activate_true_is_a_serving_change(where: str) -> None:
    edge = harness.edge("miassist")
    query = {"activate": "true"} if where == "query" else {}
    body = {"activate": True} if where == "body" else {}
    verdict = edge.check(
        "miserver", "POST", "/api/clusters/import", query, harness.HEADERS["miserver"], body
    )[1]
    assert verdict is not None and verdict.cls == classes.FORBIDDEN_ROUTE


def test_an_import_without_activate_passes() -> None:
    edge = harness.edge("miassist")
    assert (
        edge.check(
            "miserver",
            "POST",
            "/api/clusters/import",
            {"activate": "false"},
            harness.HEADERS["miserver"],
            {},
        )[1]
        is None
    )


async def test_baseline_handoff_is_counted_not_failed() -> None:
    rep = replay.Replay(edge=harness.edge("baseline"), library={}, health={})
    status, _, body = rep.handle("miserver", "POST", "/api/probes/evalfx-p/arm", {}, {}, {})
    assert status == 403 and body["refused"] == "operator_handoff"
    assert rep.state.handoffs == 1 and rep.state.failures == []


def test_the_held_state_flips_only_after_done() -> None:
    before = {"success": True, "data": {"armed": []}}
    after = {"success": True, "data": {"armed": [{"id": "evalfx-p"}]}}
    take = harness.cassette_doc(
        [
            harness.record(
                0, "miserver", "GET", "/api/probes/status", "/api/probes/status", 200, before
            ),
            harness.record(
                1, "miserver", "GET", "/api/probes/status", "/api/probes/status", 200, after
            ),
        ]
    )
    rep = replay.build(take, harness.edge("baseline"), {})
    reads = [rep.handle("miserver", "GET", "/api/probes/status", {}, {}, None)[2] for _ in range(3)]
    assert reads == [before, before, before]
    rep.state.handoffs_released.add("miserver")
    assert rep.handle("miserver", "GET", "/api/probes/status", {}, {}, None)[2] == after
