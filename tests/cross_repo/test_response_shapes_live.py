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

from tests.support import answer_contracts, siblings
from tests.support import response_shapes as rs

pytestmark = pytest.mark.cross_repo
SIBLING = {s.key: s for s in siblings.SIBLINGS}


@pytest.mark.parametrize("app", ["midataworks", "miworkbench", "miserver", "miforge"])
def test_generated_shapes_regenerate_from_the_app(app: str) -> None:
    """The generator's entries in ``responses.json`` are the app's own at the snapshot commit. A
    ``vendored`` app has none: its shapes are its answer contract, pinned byte for byte by
    ``test_answer_contracts_live.py`` (ENH-013 006, MA4)."""
    if answer_contracts.vendored(app):
        pytest.skip(f"{app} is vendored: its shapes are its answer contract, not responses.json")
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


#: miForge's own pin of its untyped WSP list rows' keys (miForge feature 020, FR-020.26): the
#: module its ``test_list_row_keys.py`` asserts the routes' real answers against.
MIFORGE_KEYS_PROBE = r"""
import json, sys
sys.path.insert(0, ".")
from tests.support import wsp_list_keys as k
sys.stdout.write("@@KEYS@@" + json.dumps({route: sorted(keys) for route, keys in k.ROW_KEYS.items()}))
"""


def test_miforge_wsp_list_overlays_carry_the_keys_miforge_pins() -> None:
    """miForge's WSP lists answer an untyped dict, so neither its OpenAPI document nor the route
    index names a row field: a re-pin that left a FU-10 overlay without a key the rows now carry
    passed every other test here (020-P2 control S3). miForge pins each row's keys from the
    routes' answers (``backend/tests/support/wsp_list_keys.py``, asserted by its
    ``test_list_row_keys.py``); each overlay's item must carry exactly those keys, at the shapes'
    own commit."""
    import subprocess

    vendored = rs.vendored()["apps"]["miforge"]
    root = siblings.require_root(SIBLING["miforge"], "miforge's pinned row keys cannot be read")
    tree, _ = snap.export(snap.RECIPES["miforge"]["folder"], vendored["commit"], repo=root)
    result = subprocess.run(
        [str(snap.interpreter("miforge", root)), "-B", "-c", MIFORGE_KEYS_PROBE],
        cwd=tree / "backend",
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert "@@KEYS@@" in result.stdout, result.stderr[-2000:]
    pinned: dict[str, list[str]] = json.loads(result.stdout.split("@@KEYS@@", 1)[1])
    assert pinned, "miForge pins no list's keys: the comparison would pass vacuously"
    overlays = {
        o["route"]: o for o in json.loads((gen.SOURCES / "miforge.json").read_text())["overlays"]
    }
    for route, keys in pinned.items():
        assert route in overlays, f"miForge pins {route}'s keys and no overlay vendors it"
        schema = overlays[route]["schema"]
        (top,) = schema["properties"]
        item = schema["properties"][top]["items"]["properties"]
        assert sorted(item) == keys, (
            f"{route}: the overlay's item keys differ from miForge's at {vendored['commit']}: "
            f"missing {sorted(set(keys) - set(item))}, extra {sorted(set(item) - set(keys))}"
        )
