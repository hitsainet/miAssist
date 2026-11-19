"""The vendored response shapes are the apps' own, regenerated (R1 review fix OR1-pb-1..5).

For each app, the generator's entries in ``tests/fixtures/openapi/responses.json`` are regenerated in the sibling's interpreter from a
``git archive`` of the snapshot's OWN commit (nothing is written in the sibling) and compared: a
hand edit of the vendored file, or a source overlay whose pointer no longer lands, fails here.
Skips loudly when the sibling is absent; fails under ``MIASSIST_REQUIRE_CROSS_REPO_CHECKS=1``.
"""

from __future__ import annotations

import json

import pytest
from scripts import snapshot_openapi as snap
from scripts import snapshot_shapes as gen

from tests.support import response_shapes as rs
from tests.support import siblings

pytestmark = pytest.mark.cross_repo
SIBLING = {s.key: s for s in siblings.SIBLINGS}


@pytest.mark.parametrize("app", ["midataworks", "miworkbench", "miserver"])
def test_generated_shapes_regenerate_from_the_app(app: str) -> None:
    """The generator's entries in ``responses.json`` are the app's own at the snapshot commit."""
    vendored = rs.vendored()["apps"][app]
    root = siblings.require_root(SIBLING[app], f"{app}'s response shapes cannot be regenerated")
    src = json.loads((gen.SOURCES / f"{app}.json").read_text())
    classes = sorted({c for o in src.get("overlays", []) for c in o.get("classes", [])})
    tree, _ = snap.export(snap.RECIPES[app]["folder"], vendored["commit"], repo=root)
    loaded = gen.emit(app, tree, classes, snap.interpreter(app, root))
    routes = gen.build(app, loaded["openapi"], loaded["models"], src)
    live = gen.entries(app, routes, rs.snapshot(app)["paths"], list(src.get("extra_routes", [])))
    mine = {
        route: {s: e for s, e in statuses.items() if e.get("generated") == gen.GENERATED}
        for route, statuses in vendored["routes"].items()
    }
    # a (route, status) a hand-derived entry holds is the hand entry's, as ``gen.write`` keeps it
    # (integration OVN-miassist-int-17)
    held = {
        (route, s)
        for route, statuses in vendored["routes"].items()
        for s, e in statuses.items()
        if e.get("generated") != gen.GENERATED
    }
    live = {
        route: {s: e for s, e in statuses.items() if (route, s) not in held}
        for route, statuses in live.items()
    }
    live = {route: statuses for route, statuses in live.items() if statuses}
    assert live == {r: s for r, s in mine.items() if s}, (
        f"{app}: the generated shapes are not the app's at {vendored['commit']}; "
        f"refresh: python -m scripts.snapshot_shapes --app {app} --ref <commit>"
    )
