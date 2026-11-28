"""The committed OpenAPI pins against each sibling's own code (001 FR-15, AC-15.3; FTASKS 4.4's
cross-repo half; R3M-6, V-8, R2M-10, R2M-12).

For each app the snapshot is REGENERATED in the sibling's own interpreter from a ``git archive`` of
its committed ``HEAD`` (or ``MIASSIST_SNAPSHOT_REF_<APP>``; nothing is written in the sibling) and
compared with ``tests/fixtures/openapi/<app>.json`` (the pinned path items) and ``<app>.index.json``
(the full route index). miWorkbench's ``CALLER_TOOLS`` and its gated routes too (the latter from its
live registry, 045-A0's ``gated_routes(app)``; OVN-miassist-w-1). miServer's conditionally gated routes
are derived from its live route table (each gated endpoint's ``when`` closure) and must equal
``MISERVER_CONDITIONAL_GATES``, with none of them registered by miAssist. Each test skips loudly
when the sibling is absent and fails under ``MIASSIST_REQUIRE_CROSS_REPO_CHECKS=1``.
"""

from __future__ import annotations

import json
import os
import subprocess
from functools import cache
from pathlib import Path
from typing import Any

import pytest
from scripts import snapshot_openapi as snap

from miassist.adapters.routes import MISERVER_CONDITIONAL_GATES, ROUTES
from tests.support import siblings

pytestmark = pytest.mark.cross_repo
PINS = Path(__file__).resolve().parents[1] / "fixtures/openapi"
SIBLING = {s.key: s for s in siblings.SIBLINGS}
APPS = ("miworkbench", "miserver", "midataworks", "miforge")

GATES_PROBE = r"""
import inspect, json, sys
sys.path.insert(0, ".")
from fastapi.routing import APIRoute, iter_route_contexts
{code}
while not hasattr(app, "routes"):
    app = app.app
gated, conditional = [], set()
for route in iter_route_contexts(app.routes):
    if not isinstance(route.original_route, APIRoute):
        continue
    if not getattr(route.endpoint, "__miserver_approval_action__", None):
        continue
    when = inspect.getclosurevars(route.endpoint).nonlocals.get("when")
    for method in sorted(route.methods or ()):
        gated.append((method, str(route.path)))
        if when is not None:
            conditional.add((method, str(route.path)))
sys.stdout.write("@@GATES@@" + json.dumps({{"gated": gated, "conditional": sorted(conditional)}}))
"""


def ref_for(app: str) -> str:
    return os.environ.get(f"MIASSIST_SNAPSHOT_REF_{app.upper()}", "HEAD")


@cache
def tree(app: str) -> tuple[Path, Path]:
    """(the exported tree, the sibling's interpreter)."""
    root = siblings.require_root(SIBLING[app], f"{app}'s OpenAPI pins cannot be regenerated")
    exported, _ = snap.export(snap.RECIPES[app]["folder"], ref_for(app), repo=root)
    return exported, snap.interpreter(app, root)


@cache
def regenerated(app: str) -> dict[str, Any]:
    exported, python = tree(app)
    return snap.emit(app, exported, python)


def pinned(app: str, suffix: str = "") -> dict[str, Any]:
    data: dict[str, Any] = json.loads((PINS / f"{app}{suffix}.json").read_text())
    return data


@pytest.mark.parametrize("app", APPS)
def test_unchanged(app: str) -> None:
    """The pinned path items equal the sibling's (V-8: regenerated, not hand-copied)."""
    live = snap.registered_items(app, regenerated(app)["openapi"])
    assert live == pinned(app)["paths"], (
        f"{app} drifted from its pin (taken at {pinned(app)['commit']}); "
        f"refresh: python -m scripts.snapshot_openapi --app {app}"
    )


@pytest.mark.parametrize("app", APPS)
def test_route_index_unchanged(app: str) -> None:
    live = snap.route_index(regenerated(app)["openapi"])
    assert live == pinned(app, ".index")["routes"], f"{app}'s route index drifted (R3M-6)"


def test_caller_tools() -> None:
    assert regenerated("miworkbench").get("caller_tools") == pinned("miworkbench")["caller_tools"]


def test_gated_route_list() -> None:
    """miWorkbench's gated routes come from its LIVE registry, not from markers (OVN-miassist-w-1):
    045-A0 keeps its gate in code (``src.core.approval_gate.gated_routes(app)``) and publishes no
    ``x-approval-action``. The regenerated ``[method, path, action]`` list equals the pin, and every
    route miAssist marks file_first is on it with the same action (001 FTASKS 4.4, 14.4)."""
    live = regenerated("miworkbench").get("gated_routes")
    assert live is not None, "this miWorkbench checkout has no gated_routes(app): 045-A0 absent"
    assert live, "gated_routes(app) found no gated route: the comparison would pass vacuously"
    assert live == pinned("miworkbench")["gated_routes"], (
        f"miWorkbench's gated routes drifted from the pin (taken at "
        f"{pinned('miworkbench')['commit']}); refresh: python -m scripts.snapshot_openapi "
        f"--app miworkbench"
    )
    gated = {(method, path): action for method, path, action in live}
    marked = [r for r in ROUTES.for_app("miworkbench") if r.file_first]
    assert marked, "no file-first miWorkbench route registered: nothing would be compared"
    for route in marked:
        assert gated.get((route.method, route.path)) == route.approval_action, (
            f"{route.id} is file-first as {route.approval_action!r}, but miWorkbench gates "
            f"{route.method} {route.path} as {gated.get((route.method, route.path))!r}"
        )
    # An app version that also publishes markers must agree with them (the marker path, kept).
    index = snap.route_index(regenerated("miworkbench")["openapi"])
    markers = {(r["method"], r["path"]) for r in index if "x-approval-action" in r}
    if markers:
        assert {(r.method, r.path) for r in marked} <= markers


def miserver_gates() -> dict[str, Any]:
    exported, python = tree("miserver")
    code = GATES_PROBE.format(code=snap.RECIPES["miserver"]["code"])
    env = {**os.environ, **snap.IMPORT_ENV}
    result = subprocess.run(
        [str(python), "-B", "-c", code],
        cwd=exported / snap.RECIPES["miserver"]["cwd"],
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    assert "@@GATES@@" in result.stdout, result.stderr[-2000:]
    loaded: dict[str, Any] = json.loads(result.stdout.split("@@GATES@@", 1)[1])
    return loaded


def test_miserver_gate_predicates() -> None:
    gates = miserver_gates()
    conditional = {tuple(pair) for pair in gates["conditional"]}
    assert gates["gated"], "no gated route found: the probe would pass vacuously"
    assert conditional == MISERVER_CONDITIONAL_GATES
    assert ("PUT", "/api/environment") in conditional
    registered_gated = {
        (r.method, r.path) for r in ROUTES.for_app("miserver") if r.gate.value == "app_gated"
    }
    assert not (registered_gated & conditional)
