"""This chain's routes in the LIVE registry (FPRD §7, FR-003.28, FR-003.23; FTASKS 1.4, 0.3, 8.3).

One pin per floor entry; the never-registered set; headers come from Core's client only.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from miassist.adapters.base import GateClass
from miassist.adapters.routes import ROUTES, UNGATED_WRITES_ALLOWED
from miassist.playbooks.detector_probe import routes as rt

SRC = Path(__file__).resolve().parents[3] / "src/miassist/playbooks"
#: FPRD FR-003.28 as this push binds it: (app, method, path) -> floor entry.
FLOOR = {
    ("miworkbench", "POST", "/api/v1/probe-monitors/behaviours"): "detector.create_behaviour",
    ("miworkbench", "POST", "/api/v1/probe-monitors/datasets"): "detector.register_views",
    (
        "miworkbench",
        "POST",
        "/api/v1/probe-monitors/nonsense-text",
    ): "detector.create_nonsense_text",
    ("miserver", "POST", "/api/probes/import"): "steering.import_probe",
}


def mine() -> list:  # type: ignore[type-arg]
    return [r for r in ROUTES if r.id.split(".", 1)[1].startswith("dp_")]


def test_every_chain_route_is_in_the_live_registry() -> None:
    assert {r.id for r in rt.DETECTOR_ROUTES} == {r.id for r in mine()}
    for route in rt.DETECTOR_ROUTES:
        assert ROUTES.get(route.id) is route


@pytest.mark.parametrize("where", sorted(FLOOR), ids=lambda w: w[2])
def test_floor_entry_pinned(where: tuple[str, str, str]) -> None:

    found = [r for r in mine() if (r.app, r.method, r.path) == where]
    assert len(found) == 1, where
    assert found[0].gate is GateClass.UNGATED_WRITE
    assert found[0].floor_entry == FLOOR[where] and FLOOR[where] in UNGATED_WRITES_ALLOWED


def test_ungated_writes_equal_the_floor_table() -> None:
    writes = {
        (r.app, r.method, r.path): r.floor_entry
        for r in mine()
        if r.gate is GateClass.UNGATED_WRITE
    }
    assert writes == FLOOR | DOWNLOAD
    assert all(r.floor_entry != "detector.file_send" for r in ROUTES)


#: Push B adds the M16 download (touches the Hub, A23).
DOWNLOAD: dict[tuple[str, str, str], str] = {
    ("miworkbench", "POST", "/api/v1/datasets/download"): "import.hf_miworkbench",
}


def test_other_chain_routes_are_reads() -> None:
    for route in mine():
        if (route.app, route.method, route.path) in FLOOR | DOWNLOAD or route.file_first:
            continue
        if (route.app, route.method, route.path) == SEND:
            continue
        assert route.gate is GateClass.READ, route.id
        assert route.method == "GET" or route.computes_only, route.id


NEVER = [
    ("miserver", "POST", "/api/probes/{probe_id}/arm"),
    ("miserver", "POST", "/api/probes/{probe_id}/parity"),
    ("miserver", "GET", "/api/probes/events/{event_id}"),
    ("miserver", "GET", "/api/probes/hub/search"),
    ("miserver", "GET", "/api/probes/hub/{repo_id}/definitions"),
    ("miserver", "POST", "/api/probes/hub/import"),
    ("midataworks", "POST", "/api/v1/generation-runs"),
    ("miworkbench", "POST", "/api/v1/mcp/approvals/{request_id}/consume"),
    ("miworkbench", "POST", "/api/v1/probe-monitors/judge-runs"),
    ("miworkbench", "POST", "/api/v1/probe-monitors/spot-checks"),
    ("miworkbench", "POST", "/api/v1/probe-monitors/judge-prompts/try"),
    ("miworkbench", "POST", "/api/v1/probe-monitors/probes/{probe_id}/publish"),
    ("miworkbench", "POST", "/api/v1/probe-monitors/behaviours/{key}/family/publish"),
]


@pytest.mark.parametrize("where", NEVER, ids=lambda w: f"{w[1]} {w[2]}")
def test_never_registered(where: tuple[str, str, str]) -> None:
    assert where not in {(r.app, r.method, r.path) for r in ROUTES}


def test_no_decide_route_and_no_enhanced_labelling() -> None:
    for route in ROUTES:
        assert not route.path.endswith(("/approve", "/deny", "/reject", "/consume")), route.id
        if route.app == "miworkbench" or route in rt.DETECTOR_ROUTES:
            # Integration (OVN-miassist-int-14): 003's ban is on its own routes and on miWorkbench's
            # publish routes; 004 registers miDataworks' gated publish routes (the operator decides).
            assert "enhanced-labeling" not in route.path and "/publish" not in route.path, route.id


def test_playbook_code_sets_no_header_and_imports_no_http() -> None:
    """FR-003.23: the agent header is Core's (set on the client); playbook modules never import
    httpx nor pass a ``headers=`` argument."""
    for path in sorted((SRC / "detector_probe").rglob("*.py")) + sorted(
        (SRC / "_shared").rglob("*.py")
    ):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import | ast.ImportFrom):
                names = [a.name for a in node.names] + [getattr(node, "module", "") or ""]
                assert not any(n.startswith("httpx") for n in names), path.name
            if isinstance(node, ast.Call):
                assert all(k.arg != "headers" for k in node.keywords), path.name


def test_download_touches_the_hub_and_forbids_a_token() -> None:
    from miassist.adapters.base import ANY

    route = R_DOWNLOAD()
    assert route.touches_hub and route.hub_repo_param == "body.repo_id"
    assert route.hub_repo_type == "dataset" and route.forbidden["body.access_token"] is ANY


def R_DOWNLOAD():  # type: ignore[no-untyped-def]  # noqa: N802
    return next(r for r in ROUTES if (r.method, r.path) == ("POST", "/api/v1/datasets/download"))


#: R3M-2: every miWorkbench GPU route this chain registers is file-first with 045's action.
FILE_FIRST = {
    "/api/v1/probe-monitors/runs": "start_probe_training_run",
    "/api/v1/probe-monitors/probes/{probe_id}/evaluate": "evaluate_probe_monitor",
    "/api/v1/probe-monitors/probes/{probe_id}/definition": "build_probe_definition",
}
SEND = ("midataworks", "POST", "/api/v1/detector-sets/send")


def test_the_send_is_gated_never_on_the_floor() -> None:
    """FR-003.28, A25: the send's gate is unconditional (``x-approval-when: always``), so it is
    ``app_gated`` (server runs it), with no floor entry; ``detector.file_send`` binds nothing."""
    found = [r for r in mine() if (r.app, r.method, r.path) == SEND]
    assert len(found) == 1
    assert found[0].gate is GateClass.APP_GATED and not found[0].file_first
    assert found[0].floor_entry is None


def test_gpu_routes_are_file_first_with_their_action() -> None:
    gated = {r.path: r for r in mine() if r.app == "miworkbench" and r.gate is GateClass.APP_GATED}
    assert set(gated) >= set(FILE_FIRST)
    for path, action in FILE_FIRST.items():
        assert gated[path].file_first and gated[path].approval_action == action, path
    assert all(r.file_first for r in gated.values())
