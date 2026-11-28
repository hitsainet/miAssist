"""FR-002.7: every milestone (each alternative) and every profile and fairness route resolves in
the reference OpenAPI of its app."""

from __future__ import annotations

from miassist_eval import goals, openapi_ref
from tests.support import harness


def test_every_milestone_alternative_resolves() -> None:
    refs = harness.refs()
    missing = []
    for g in goals.load().goals:
        for m in g["milestones"]:
            for alt in m["any_of"]:
                if refs[alt["app"]].route(alt["method"], alt["route"]) is None:
                    missing.append(
                        f"{g['id']}.{m['id']}: {alt['app']} {alt['method']} {alt['route']}"
                    )
    assert missing == []


def test_every_fairness_list_resolves() -> None:
    refs = harness.refs()
    missing = [
        f"{g['id']}: {e['app']} GET {e['route']}"
        for g in goals.load().goals
        for e in g["fairness"]["lists"]
        if refs[e["app"]].route("GET", e["route"]) is None
    ]
    assert missing == []


def test_every_profile_route_resolves() -> None:
    refs = harness.refs()
    missing = [
        f"{app}: {r['method']} {r['route']}"
        for app, prof in harness.profiles().items()
        for r in prof["routes"]
        if refs[app].route(r["method"], r["route"]) is None
    ]
    assert missing == []


def test_literal_segments_win() -> None:
    doc = harness.refs()["miserver"]
    assert (
        openapi_ref.resolve(doc, "GET", "/api/approvals/actions").template
        == "/api/approvals/actions"
    )
    assert (
        openapi_ref.resolve(doc, "GET", "/api/approvals/a1").template
        == "/api/approvals/{approval_id}"
    )
