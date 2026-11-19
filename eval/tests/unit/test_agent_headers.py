"""FPRD §6, R1M-15: each app's own agent header value, from its profile, pinned to Core's
HEADERS; a miWorkbench request carrying ``agent:miassist`` fails ``missing_agent_header``."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from miassist_eval import classes
from tests.support import harness

CORE_HEADERS = Path(__file__).resolve().parents[3] / "src/miassist/adapters/base.py"
EXPECTED = {
    "miworkbench": ("X-MiStudio-Agent", "miassist"),
    "miserver": ("X-miLLM-Agent", "agent:miassist"),
    "midataworks": ("X-Dataworks-Agent", "agent:miassist"),
    "miforge": ("X-Miforge-Agent", "agent:miassist"),
}


def core_headers() -> dict:
    """Core's HEADERS constant, read as data from its source (FR-002.1: never imported)."""
    tree = ast.parse(CORE_HEADERS.read_text())
    for node in ast.walk(tree):
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            target = node.targets[0] if isinstance(node, ast.Assign) else node.target
            if isinstance(target, ast.Name) and target.id == "HEADERS" and node.value is not None:
                value = node.value
                if isinstance(value, ast.Call) and value.args:  # MappingProxyType({...})
                    value = value.args[0]
                return ast.literal_eval(value)
    raise AssertionError("HEADERS not found in Core's adapters/base.py")


def test_profiles_carry_each_apps_own_value() -> None:
    for app, prof in harness.profiles().items():
        assert (prof["agent_header"]["name"], prof["agent_header"]["value"]) == EXPECTED[app]


def test_profiles_agree_with_cores_headers() -> None:
    core = core_headers()
    for app, prof in harness.profiles().items():
        name, value = prof["agent_header"]["name"], prof["agent_header"]["value"]
        assert core[app] == {name: value} or core[app] == (name, value), (app, core[app])


@pytest.mark.parametrize(("value", "ok"), [("miassist", True), ("agent:miassist", False)])
def test_miworkbench_wants_miassist_without_colon(value: str, ok: bool) -> None:
    edge = harness.edge()
    verdict = edge.check(
        "miworkbench", "GET", "/api/v1/datasets", {}, {"X-MiStudio-Agent": value}, None
    )[1]
    if ok:
        assert verdict is None
    else:
        assert verdict is not None and verdict.cls == classes.MISSING_AGENT_HEADER
        assert verdict.body["expected"]["value"] == "miassist"


@pytest.mark.parametrize("app", ["miserver", "midataworks", "miforge"])
def test_other_apps_want_agent_miassist(app: str) -> None:
    edge = harness.edge()
    name = EXPECTED[app][0]
    path = {
        "miserver": "/api/clusters",
        "midataworks": "/api/v1/datasets",
        "miforge": "/api/v1/approvals",
    }[app]
    assert edge.check(app, "GET", path, {}, {name: "agent:miassist"}, None)[1] is None
    bad = edge.check(app, "GET", path, {}, {name: "miassist"}, None)
    assert bad[1] is not None and bad[1].cls == classes.MISSING_AGENT_HEADER


def test_the_baseline_surface_does_not_require_miassists_header() -> None:
    edge = harness.edge("baseline")
    assert edge.check("miworkbench", "GET", "/api/v1/datasets", {}, {}, None)[1] is None
