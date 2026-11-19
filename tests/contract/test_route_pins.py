"""Route pins: the write floor, the snapshots and gate agreement (001 FTASKS 4.3, 4.4).

Everything here reads the LIVE registry (``ROUTES``) and the committed snapshots under
``tests/fixtures/openapi/``; the cross-repo half regenerates the snapshots from each sibling.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from miassist.adapters.base import GateClass, ProgrammingError, Route
from miassist.adapters.routes import (
    ROUTES,
    UNGATED_WRITES_ALLOWED,
    RouteRegistry,
    UnknownGate,
    classify_marker,
    when_tokens,
)
from miassist.playbooks.detector_probe.routes import DETECTOR_ROUTES
from tests.support.vectors import VECTORS_FILE, VECTORS_VENDORED

SNAPSHOT_WORKBENCH = Path(__file__).resolve().parents[1] / "fixtures/openapi/miworkbench.json"

OPENAPI = Path(__file__).resolve().parents[1] / "fixtures" / "openapi"
APPS = ("miworkbench", "miserver", "midataworks", "miforge")

#: A literal copy of PADR ADR-006's write-floor table (fourteen entries, A25, A34).
PADR_FLOOR_TABLE = {
    "detector.create_behaviour",
    "detector.register_views",
    "detector.create_nonsense_text",
    "steering.import_probe",
    "dataset.create",
    "dataset.save_recipe",
    "dataset.build_version",
    "dataset.build_files",
    "steering.save_profile",
    "steering.import_cluster",
    "steering.import_circuit",
    "steering.test_chat",
    "import.hf_miworkbench",
    "import.hf_midataworks",
}


def snapshot(app: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((OPENAPI / f"{app}.json").read_text())
    return data


def index(app: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = json.loads((OPENAPI / f"{app}.index.json").read_text())["routes"]
    return rows


def operation(app: str, route: Route) -> dict[str, Any]:
    op: dict[str, Any] = snapshot(app)["paths"][route.path][route.method.lower()]
    return op


# -- 4.3: the write floor -------------------------------------------------------------------------


def test_write_floor_set_equals_table() -> None:
    assert len(PADR_FLOOR_TABLE) == 14
    assert UNGATED_WRITES_ALLOWED == PADR_FLOOR_TABLE
    assert "detector.file_send" not in UNGATED_WRITES_ALLOWED
    assert "dataset.run_checks" not in UNGATED_WRITES_ALLOWED


def test_write_floor_registrations() -> None:
    writes = [r for r in ROUTES if r.gate is GateClass.UNGATED_WRITE]
    assert writes, "the registry has no ungated write: the test would pass vacuously"
    for route in writes:
        assert route.floor_entry in UNGATED_WRITES_ALLOWED, route.id
    # Core binds only the Hub check (search and preview) to the floor, both to import.hf_midataworks;
    # each playbook chain pins its own bindings (003: tests/playbooks/detector_probe/test_routes.py)
    # or adds its literal rows here (004: FPRD FR-004.21's table).
    detector_ids = {r.id for r in DETECTOR_ROUTES}
    assert {r.id: r.floor_entry for r in writes if r.id not in detector_ids} == {
        "midataworks.hf_search": "import.hf_midataworks",
        "midataworks.hf_preview": "import.hf_midataworks",
        # 004 dataset playbook (FR-004.21)
        "midataworks.hf_import": "import.hf_midataworks",
        "midataworks.create_dataset": "dataset.create",
        "midataworks.save_recipe": "dataset.save_recipe",
        "midataworks.build_version": "dataset.build_version",
        "midataworks.build_files": "dataset.build_files",
        # 005 steering playbook (FR-005.22)
        "miworkbench.save_profile": "steering.save_profile",
        "miserver.import_cluster": "steering.import_cluster",
        "miserver.import_circuit": "steering.import_circuit",
        "miserver.test_chat": "steering.test_chat",
    }


@pytest.mark.parametrize("entry", [None, "made.up_entry"])
def test_ungated_write_outside_the_floor_is_refused(entry: str | None) -> None:
    bad = Route(
        "miserver.cluster_activate_as_write",
        "miserver",
        "POST",
        "/api/clusters/fixture/{cluster_id}/start",
        GateClass.UNGATED_WRITE,
        "a write outside the floor",
        floor_entry=entry,
    )
    with pytest.raises(ProgrammingError):
        RouteRegistry((bad,))


#: POST routes registered as reads because they write nothing and are never gated (a literal list:
#: a new one is added here with its reason, never inferred). 004: miDataworks' dry runs.
POST_READS = {
    "midataworks.validate_operator": "operators.py:305, validates one step's params",
    "midataworks.validate_recipe": "recipes.py:141, validates a recipe body",
    "midataworks.plan_version": "versions.py:62-68, 'Writes nothing; never gated'",
}


def test_reads_are_gets_or_gate_machinery() -> None:
    posts = set()
    for route in ROUTES:
        if route.gate is GateClass.READ and not route.gate_machinery and route.method != "GET":
            posts.add(route.id)
            # 003's rule: a POST read is ``computes_only`` (reviewed in test_computes_only.py)
            assert route.computes_only, route.id
    # 004's literal list is among them (the merged set lives in test_computes_only.REVIEWED)
    assert posts >= set(POST_READS)


# -- 4.4: snapshots and gate agreement --------------------------------------------------------------


@pytest.mark.parametrize("app", APPS)
def test_snapshot(app: str) -> None:
    pinned = snapshot(app)["paths"]
    for route in ROUTES.for_app(app):
        assert route.method.lower() in pinned.get(
            route.path, {}
        ), f"{route.id} is not in the snapshot"
    assert {(r["method"], r["path"]) for r in index(app)} >= {
        (r.method, r.path) for r in ROUTES.for_app(app)
    }


@pytest.mark.parametrize("app", APPS)
def test_gate_agreement(app: str) -> None:
    """A marker never means ``read``; each app's rule (AC-15.3 as restated, V-7)."""
    for route in ROUTES.for_app(app):
        op = operation(app, route)
        if app == "miworkbench":
            if route.file_first:
                assert route.approval_action in snapshot(app)["caller_tools"]
            continue
        marked = classify_marker(app, route.method, route.path, op)
        if marked is None:
            continue
        assert marked is route.gate, route.id
        if marked is GateClass.UNGATED_WRITE:
            assert route.floor_entry in UNGATED_WRITES_ALLOWED
            assert route.gate_when == when_tokens(op), route.id


def test_hf_preview_is_registered_from_022s_marker() -> None:
    op = operation("midataworks", ROUTES.get("midataworks.hf_preview"))
    assert op["x-approval-when"] == "field:body.access_token"
    assert classify_marker("midataworks", "POST", "/api/v1/sources/hf/preview", op) is (
        GateClass.UNGATED_WRITE
    )


def test_pre_022_marker_without_when_is_refused() -> None:
    """NC-A33-1's shape: a marked miDataworks route with no ``x-approval-when`` is refused."""
    with pytest.raises(UnknownGate):
        classify_marker(
            "midataworks",
            "POST",
            "/api/v1/sources/hf/preview",
            {"x-approval-action": "secret_write"},
        )


def test_miworkbench_gpu_routes_are_file_first() -> None:
    """Never vacuous (V-4; R3M-2, A38). Per route from the vendored vectors (001-V): every
    registered miWorkbench route on 045's gated list is ``app_gated`` + ``file_first`` with an
    ``approval_action`` in ``CALLER_TOOLS``; every miWorkbench route registered ``app_gated`` is on
    the list; every other miWorkbench route is a read or the approval machinery. Runs over
    production ``ROUTES`` only (fixtures live on the test registry, V-2)."""
    workbench = ROUTES.for_app("miworkbench")
    assert workbench, "no miWorkbench route registered: the check would be vacuous"
    assert VECTORS_VENDORED, "001-V vendors the per-route vectors"
    vectors = json.loads(VECTORS_FILE.read_text())["vectors"]
    gated = {(v["method"], v["route"]): v["action"] for v in vectors}
    assert len(gated) == len(vectors) and gated, "one vector per gated route"
    caller_tools = set(json.loads(SNAPSHOT_WORKBENCH.read_text())["caller_tools"])
    for route in workbench:
        key = (route.method, route.path)
        if key in gated:
            assert route.gate is GateClass.APP_GATED and route.file_first, route.id
            assert route.approval_action == gated[key], route.id
            assert route.approval_action in caller_tools, route.id
        else:
            assert route.gate is not GateClass.APP_GATED, f"{route.id}: gated but not on 045's list"
            assert (
                route.gate_machinery
                or (route.gate is GateClass.READ and (route.method == "GET" or route.computes_only))
                or (
                    route.gate is GateClass.UNGATED_WRITE
                    and route.floor_entry in UNGATED_WRITES_ALLOWED
                )
            ), f"{route.id} is a miWorkbench write outside 045's gated list and the floor"


def test_pinned_gated_routes_agree() -> None:
    """001-W (FTASKS 14.4; OVN-miassist-w-1): the gated list derived from miWorkbench's live
    registry and pinned in the snapshot equals the vendored vectors' rows, and every file-first
    miWorkbench route is on it with its action. The cross-repo half regenerates the pin."""
    pinned = json.loads(SNAPSHOT_WORKBENCH.read_text())["gated_routes"]
    assert pinned and pinned == sorted(pinned), "the pin is a sorted, non-empty list"
    gated = {(method, path): action for method, path, action in pinned}
    assert len(gated) == len(pinned), "one row per gated route"
    vectors = json.loads(VECTORS_FILE.read_text())["vectors"]
    assert gated == {(v["method"], v["route"]): v["action"] for v in vectors}
    marked = [r for r in ROUTES.for_app("miworkbench") if r.file_first]
    assert marked, "no file-first miWorkbench route registered: the check would be vacuous"
    for route in marked:
        assert gated.get((route.method, route.path)) == route.approval_action, route.id


# -- R1 review fix (OR1-001-2), 2026-11-16: `always` is the app's gate, never the write floor ----


def test_always_is_app_gated() -> None:
    op = {"x-approval-action": "publish", "x-approval-when": "always"}
    assert classify_marker("midataworks", "POST", "/api/v1/x", op) is GateClass.APP_GATED


@pytest.mark.parametrize(
    "when", ["field:body.x", "state:agent_label_plan_or_sensitivity_lowering", "field:a,state:b"]
)
def test_field_and_state_are_conditional(when: str) -> None:
    op = {"x-approval-action": "build", "x-approval-when": when}
    assert classify_marker("midataworks", "POST", "/api/v1/x", op) is GateClass.UNGATED_WRITE


@pytest.mark.parametrize("when", ["always,field:body.x", "sometimes", ""])
def test_mixed_or_unknown_when_is_refused(when: str) -> None:
    op = {"x-approval-action": "publish", "x-approval-when": when}
    with pytest.raises(UnknownGate):
        classify_marker("midataworks", "POST", "/api/v1/x", op)
