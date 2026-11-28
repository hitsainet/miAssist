"""The evaluation reads list shapes from the vendored answer contracts as Core does (ENH-013 006,
FR-006.11, AT2; FTASKS 1.6 to 1.8).

``openapi_ref.contract_shape`` is the evaluation's own reader of ``docs/schemas/<app>-answers-v1.json``:
the harness imports no Core module (``test_boundary.py``). Core's reader is
``tests/support/answer_contracts.py``. The two must inline every answer identically, so Core's is
loaded here BY PATH (a test-only read of a standard-library module, never an ``import`` of Core) and
compared on every ``responses`` entry of:
- every contract Core has vendored (none before 006-1: then the test asserts there are none, and that
  Core's states agree, so it cannot pass vacuously once a copy lands);
- the synthetic contract (``tests/support/synthetic_contract.py``), always, so the comparison itself
  is exercised before any app is vendored.

The list rules (FU-10) are held too: a contract names a list's ``items`` and ``id`` before the
reference and Core's hand shapes (M16 removes that branch), and it never adds a list entry (M17).
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from miassist_eval import openapi_ref

EVAL_ROOT = Path(__file__).resolve().parents[2]
REPO = EVAL_ROOT.parent
SCRIPT = EVAL_ROOT / "scripts" / "write_route_profiles.py"


def by_path(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    saved = list(sys.path)
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path[:] = saved
    return module


CORE = by_path("_core_answer_contracts", REPO / "tests" / "support" / "answer_contracts.py")
SYNTHETIC = by_path(
    "_core_synthetic_contract", REPO / "tests" / "support" / "synthetic_contract.py"
)


def core_vendored() -> set[str]:
    return {app for app in CORE.APPS if CORE.vendored(app)}


def entries(doc: dict[str, Any]) -> list[tuple[str, str, str]]:
    return [
        (*route.split(" ", 1), status)
        for route, statuses in doc["responses"].items()
        for status in statuses
        if CORE.STATUS.match(status)
    ]


def compare(app: str, doc: dict[str, Any]) -> int:
    """Both readers on every entry of ``doc`` (read by the evaluation from its file); the count."""
    core = CORE.Contract(app, doc)
    compared = 0
    for method, template, status in entries(doc):
        mine = openapi_ref.contract_schema(app, method, template, status)
        assert mine == core.inlined(method, template, status), f"{app} {method} {template} {status}"
        compared += 1
    return compared


def test_the_readers_agree_on_which_apps_are_vendored() -> None:
    assert set(CORE.APPS) == set(openapi_ref.APPS)
    on_disk = {app for app in openapi_ref.APPS if openapi_ref.answer_contract(app) is not None}
    assert on_disk == core_vendored(), "a copy exists exactly when Core's state is vendored"


def test_the_readers_agree_on_every_vendored_contract() -> None:
    vendored = sorted(core_vendored())
    if not vendored:
        assert all(openapi_ref.answer_contract(app) is None for app in openapi_ref.APPS)
        return
    for app in vendored:
        doc = openapi_ref.answer_contract(app)
        assert doc is not None
        assert compare(app, doc) == len(entries(doc)) > 0, app


def install(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, doc: dict[str, Any] | None) -> None:
    """Point the evaluation at ``tmp_path`` holding ``doc`` as miServer's contract (or nothing)."""
    folder = tmp_path / ("synthetic" if doc is not None else "none")
    folder.mkdir()
    if doc is not None:
        (folder / f"{SYNTHETIC.APP}-answers-v1.json").write_text(json.dumps(doc))
    monkeypatch.setenv("MIASSIST_ANSWER_CONTRACTS_DIR", str(folder))


def test_the_readers_agree_on_the_synthetic_contract(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    doc = SYNTHETIC.document()
    install(tmp_path, monkeypatch, doc)
    assert compare(SYNTHETIC.APP, doc) == len(entries(doc)) >= 9
    tree = openapi_ref.contract_schema(SYNTHETIC.APP, "GET", "/api/tree", 200)
    assert set(tree["$defs"]) == {"Node"}, "a self-reference is carried, not unrolled"
    assert (
        openapi_ref.contract_schema(SYNTHETIC.APP, "GET", "/api/health/metrics/prometheus", 200)
        is None
    )
    assert openapi_ref.contract_shape(SYNTHETIC.APP, "POST", "/api/probes/import") is not None


def test_an_excluded_route_has_no_shape_in_either_reader(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``excluded`` wins over a ``responses`` entry for the same route, in both readers. miServer's
    contract keeps them disjoint, so dropping the check survived (006-1 review, E3)."""
    route = "GET /api/health/metrics/prometheus"
    doc = SYNTHETIC.document(responses={**SYNTHETIC.RESPONSES, route: {"200": {"type": "object"}}})
    install(tmp_path, monkeypatch, doc)
    method, template = route.split(" ", 1)
    assert openapi_ref.contract_schema(SYNTHETIC.APP, method, template, 200) is None
    assert openapi_ref.contract_shape(SYNTHETIC.APP, method, template) is None
    assert CORE.Contract(SYNTHETIC.APP, doc).inlined(method, template, 200) is None


# -- the list rules (FU-10) under a contract ---------------------------------------------------

#: miServer routes the reference leaves open and no hand shape keys (``GET /api/probes/events``,
#: whose reference answer is open; re-chosen after train A1's re-pin typed ``/api/probes/behaviours``),
#: or answers without an array (``GET /api/approvals/{approval_id}``).
OPEN_LIST = "/api/probes/events"
NOT_A_LIST = "/api/approvals/{approval_id}"


def list_contract() -> dict[str, Any]:
    responses = {
        **SYNTHETIC.RESPONSES,
        f"GET {OPEN_LIST}": {"200": {"$ref": "#/$defs/PageOf_ProbeListItem_"}},
        f"GET {NOT_A_LIST}": {"200": {"items": {"$ref": "#/$defs/ProbeListItem"}, "type": "array"}},
    }
    doc: dict[str, Any] = SYNTHETIC.document(responses=responses)
    return doc


def profile_routes() -> dict[tuple[str, str], dict[str, Any]]:
    data = by_path("write_route_profiles", SCRIPT).profile("miserver")
    return {(e["method"], e["route"]): e for e in data["routes"]}


def test_a_contract_keys_a_list_the_reference_leaves_open(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """M16's case: only the contract says where ``GET /api/probes/events``' items are. "Before" reads
    no contract at all, so the case holds whatever Core has vendored."""
    install(tmp_path, monkeypatch, None)
    before = profile_routes()[("GET", OPEN_LIST)]
    assert before["list"] == {"items": "*"}, before
    install(tmp_path, monkeypatch, list_contract())
    after = profile_routes()[("GET", OPEN_LIST)]
    assert after["list"] == {"items": "data", "id": "id"}, after


def test_a_contract_never_adds_a_list_entry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """M17's case (FU-10's limit): the contract types ``GET /api/approvals/{approval_id}`` as an
    array, but the reference decides which routes are lists, so the entry count is unchanged."""
    install(tmp_path, monkeypatch, None)
    before = profile_routes()
    install(tmp_path, monkeypatch, list_contract())
    after = profile_routes()
    lists = sorted(k for k, e in before.items() if "list" in e)
    assert sorted(k for k, e in after.items() if "list" in e) == lists
    assert sorted(after) == sorted(before)
    assert "list" not in after[("GET", NOT_A_LIST)]
