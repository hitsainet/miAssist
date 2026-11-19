"""FR-002.14c (static): every reference GET whose 2xx schema holds an array of objects has a
``list`` entry or ``list: none`` with a reason."""

from __future__ import annotations

import pytest

from miassist_eval import allowed, cassette
from tests.support import harness

#: Written here, independent of the profiles: lists the goals and the relay read.
KNOWN_LISTS = [
    ("midataworks", "/api/v1/datasets"),
    ("midataworks", "/api/v1/approvals"),
    ("midataworks", "/api/v1/versions"),
    ("miworkbench", "/api/v1/datasets"),
    ("miworkbench", "/api/v1/probe-monitors/behaviours"),
    ("miworkbench", "/api/v1/mcp/approvals"),
    ("miserver", "/api/probes"),
    ("miserver", "/api/clusters"),
    ("miforge", "/api/v1/approvals"),
]


@pytest.mark.parametrize("app", ["miworkbench", "miserver", "midataworks", "miforge"])
def test_no_uncovered_list_route(app: str) -> None:
    assert allowed.uncovered_list_routes(harness.refs()[app], harness.profiles()[app]) == []


@pytest.mark.parametrize(("app", "route"), KNOWN_LISTS)
def test_known_list_has_a_filtering_entry(app: str, route: str) -> None:
    entry = cassette.route_entry(harness.profiles()[app], "GET", route)
    assert entry is not None and isinstance(entry.get("list"), dict), f"{app} {route}"


def test_list_none_always_has_a_reason() -> None:
    for app, prof in harness.profiles().items():
        for r in prof["routes"]:
            if r.get("list") == "none":
                assert r.get("reason"), f"{app} {r['route']}"


def test_the_static_check_finds_a_dropped_entry() -> None:
    prof = harness.profiles()["midataworks"]
    prof["routes"] = [r for r in prof["routes"] if r["route"] != "/api/v1/datasets"]
    assert "GET /api/v1/datasets" in allowed.uncovered_list_routes(
        harness.refs()["midataworks"], prof
    )
