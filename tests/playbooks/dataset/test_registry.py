"""The dataset playbook's wiring, read from the LIVE registries (004 FTASKS 0.1, 0.2, 1.1, 1.3,
1.4, 1.6, 1.7, 7.1; FPRD FR-004.1 - FR-004.3, FR-004.16 - FR-004.18, FR-004.21).

Every assertion reads what a client or Core's guards see (``tools/list``, ``prompts/list``, the
skill resource, ``PROVIDERS``, ``ROUTES``), never this chain's source text. Deleting any
registration line turns a test here red (controls in ``0xcc/reviews/004_mutations.md``).
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from types import MappingProxyType
from typing import Any

import pytest
from mcp import Client

from miassist.adapters import dataset as dw
from miassist.adapters.base import ANY, GateClass, ProgrammingError, Route
from miassist.adapters.routes import ROUTES, RouteRegistry, UnknownGate, check_registration
from miassist.contracts.playbook import Playbook
from miassist.playbooks.registry import PlaybookError, _validate
from miassist.playbooks.status import PROVIDERS
from tests.support.fake_apps import all_fakes
from tests.support.servers import make_server

DEFINITION = Path(__file__).resolve().parents[3] / "src/miassist/playbooks/definitions/dataset.json"
TOOLS = {
    "miassist_dataset_find": (
        "Find a public dataset",
        {"query", "licence", "limit"},
    ),
    "miassist_dataset_build": (
        "Build a dataset version",
        {"source", "config", "split", "revision", "name", "text_column", "label_column", "recipe"},
    ),
    "miassist_dataset_check": (
        "Check a dataset version",
        {"dataset", "version", "check_run_id"},
    ),
    "miassist_dataset_publish": (
        "Publish a dataset version",
        {"dataset", "repo_id", "version", "visibility", "card_prose", "ask_again", "confirm"},
    ),
}

# -- 1.1 the definition ---------------------------------------------------------------------------


def test_definition_validates_and_is_ftid_3_1() -> None:
    raw = json.loads(DEFINITION.read_text())
    playbook = _validate(raw, "dataset.json")
    assert playbook.id == "dataset" and str(playbook.requires_apps[0].value) == "midataworks"
    assert [s.id for s in playbook.steps] == ["find", "build", "check", "publish"]
    assert [s.tool.root for s in playbook.steps] == list(TOOLS)
    assert [s.entry for s in playbook.steps] == [True, False, False, False]
    assert [(s.done_when.pointer, s.done_when.op) for s in playbook.steps] == [
        ("/candidates/0", "exists"),
        ("/version_ready", "truthy"),
        ("/checks_complete", "truthy"),
        ("/publish_status", "in"),
    ]
    assert playbook.steps[3].done_when.value == ["published", "no_change"]


@pytest.mark.parametrize("field", ["title", "goal", "requires_apps", "steps", "kind", "version"])
def test_definition_missing_a_required_field_is_refused_by_name(field: str) -> None:
    raw = json.loads(DEFINITION.read_text())
    del raw[field]
    with pytest.raises(PlaybookError, match=field):
        _validate(raw, "dataset.json")


def test_every_text_field_is_a_key() -> None:
    raw = json.loads(DEFINITION.read_text())
    playbook = Playbook.model_validate(raw)
    keys = [playbook.title.root, playbook.goal.root]
    for s in playbook.steps:
        assert s.title is not None
        keys += [s.title.root, s.explain_beginner.root, s.explain_expert.root]
        keys.append(s.done_when.description.root)
    assert all(k.startswith("dataset.") and " " not in k for k in keys)


# -- 1.4 / 1.6 the live registry -----------------------------------------------------------------


async def listed(installed: tuple[str, ...]) -> tuple[dict[str, Any], list[str]]:
    mcp, _ = make_server(installed, all_fakes())
    async with Client(mcp) as client:
        tools = {t.name: t for t in (await client.list_tools()).tools}
        prompts = [p.name for p in (await client.list_prompts()).prompts]
    return tools, prompts


@pytest.mark.parametrize("installed", [("midataworks",), ("miworkbench", "midataworks", "miforge")])
async def test_four_tools_registered_with_titles_hints_and_arguments(
    installed: tuple[str, ...],
) -> None:
    tools, _ = await listed(installed)
    for name, (title, arguments) in TOOLS.items():
        tool = tools[name]
        assert tool.title == title, name
        hints = tool.annotations
        assert hints.read_only_hint is False and hints.destructive_hint is False, name
        assert hints.idempotent_hint is None and hints.open_world_hint is None, name
        assert set(tool.input_schema["properties"]) == arguments, name
        assert tool.input_schema.get("additionalProperties") is False, name
        assert tool.output_schema is not None, name


async def test_the_find_is_annotated_write() -> None:
    """R1M-28, A23: the find starts search and preview jobs, so it is not read-only."""
    tools, _ = await listed(("midataworks",))
    assert tools["miassist_dataset_find"].annotations.read_only_hint is False


@pytest.mark.parametrize("installed", [("miworkbench",), ("miserver", "miforge"), ()])
async def test_absent_without_midataworks(installed: tuple[str, ...]) -> None:
    tools, prompts = await listed(installed)
    assert not set(TOOLS) & set(tools)
    assert "dataset" not in prompts


async def test_prompt_and_skill_registered() -> None:
    mcp, deps = make_server(("midataworks",), all_fakes())
    async with Client(mcp) as client:
        prompts = [p.name for p in (await client.list_prompts()).prompts]
        assert "dataset" in prompts
        prompt = await client.get_prompt("dataset", {})
        assert "miassist_dataset_find" in prompt.messages[0].content.text
        skill = await client.read_resource("miassist://skills/dataset")
        assert skill.contents[0].text.startswith("---\nname: dataset\n")
    assert deps.playbooks is not None and deps.playbooks.get("dataset") is not None
    assert deps.playbooks.get("dataset").offered  # type: ignore[union-attr]


def test_status_provider_registered() -> None:
    from miassist.playbooks.dataset.status import PROVIDER

    assert PROVIDERS["dataset"] is PROVIDER


async def test_status_dispatches_to_the_provider() -> None:
    mcp, _ = make_server(("midataworks",), all_fakes())
    async with Client(mcp) as client:
        result = await client.call_tool("miassist_status", {"playbook": "dataset"})
    playbook = result.structured_content["data"]["playbook"]
    assert playbook["playbook_id"] == "dataset" and playbook["where"] == "find"


# -- 1.3 / 1.7 / 0.2 the routes and the floor ----------------------------------------------------

#: FPRD FR-004.21's table, written out (one pin per ungated write).
FLOOR = {
    "midataworks.hf_import": (
        "POST",
        "/api/v1/sources/hf",
        "import.hf_midataworks",
        ("field:body.access_token",),
        True,
        {"body.access_token": ANY, "body.confirm_large": ANY},
    ),
    "midataworks.create_dataset": ("POST", "/api/v1/datasets", "dataset.create", (), False, {}),
    "midataworks.save_recipe": ("POST", "/api/v1/recipes", "dataset.save_recipe", (), False, {}),
    "midataworks.build_version": (
        "POST",
        "/api/v1/versions",
        "dataset.build_version",
        ("state:agent_label_plan_or_sensitivity_lowering",),
        False,
        {},
    ),
    "midataworks.build_files": (
        "POST",
        "/api/v1/versions/{version_id}/publish-builds",
        "dataset.build_files",
        (),
        False,
        {},
    ),
}


@pytest.mark.parametrize("route_id", sorted(FLOOR))
def test_floor_pin(route_id: str) -> None:
    method, path, entry, when, hub, forbidden = FLOOR[route_id]
    route = ROUTES.get(route_id)
    assert (route.method, route.path) == (method, path)
    assert route.gate is GateClass.UNGATED_WRITE
    assert route.floor_entry == entry
    assert route.gate_when == when
    assert route.touches_hub is hub
    assert dict(route.forbidden) == forbidden
    for name, value in forbidden.items():
        assert route.forbidden[name] is value


def test_the_chains_ungated_writes_are_exactly_the_table() -> None:
    mine = {r.id for r in dw.DATASET_ROUTES if r.gate is GateClass.UNGATED_WRITE}
    assert mine == set(FLOOR)
    registered = {r.id for r in ROUTES if r.app == "midataworks"}
    assert {r.id for r in dw.DATASET_ROUTES} <= registered


def test_publish_is_the_one_gated_write() -> None:
    route = ROUTES.get("midataworks.publish")
    assert (route.method, route.path, route.gate) == (
        "POST",
        "/api/v1/publishes",
        GateClass.APP_GATED,
    )
    gated = [r.id for r in dw.DATASET_ROUTES if r.gate is GateClass.APP_GATED]
    assert gated == ["midataworks.publish"]


def test_no_route_can_carry_a_repo_id_but_the_publish() -> None:
    """A34: no registered route of this playbook takes a repo_id except the gated publish (the
    import names its source repository and is the Hub-checked floor entry)."""
    import json as _json

    snap = _json.loads(
        (Path(__file__).resolve().parents[2] / "fixtures/openapi/midataworks.json").read_text()
    )
    for route in dw.DATASET_ROUTES:
        if route.method == "GET" or route.id in ("midataworks.publish", "midataworks.hf_import"):
            continue
        op = snap["paths"][route.path][route.method.lower()]
        schema = (
            op.get("requestBody", {})
            .get("content", {})
            .get("application/json", {})
            .get("schema", {})
        )
        assert "repo_id" not in schema.get("properties", {}), route.id


NEVER = [
    ("POST", "/api/v1/versions/{version_id}/publish-checks"),
    ("POST", "/api/v1/versions/{version_id}/leakage"),
    ("POST", "/api/v1/recipes/{recipe_id}/build"),
    ("POST", "/api/v1/sources/uploads"),
    ("POST", "/api/v1/generation-runs"),
    ("POST", "/api/v1/label-runs"),
    ("PUT", "/api/v1/settings/hf_token"),
    ("POST", "/api/v1/approvals/{approval_id}/approve"),
    ("POST", "/api/v1/approvals/{approval_id}/reject"),
    ("POST", "/api/v1/approvals/approve-batch"),
]


@pytest.mark.parametrize("method,path", NEVER)
def test_never_registered(method: str, path: str) -> None:
    assert all((r.method, r.path) != (method, path) for r in ROUTES)


def test_run_checks_is_not_on_the_floor() -> None:
    assert all(r.floor_entry != "dataset.run_checks" for r in ROUTES)


def _with(route: Route, **changes: Any) -> Route:
    fields = {f: getattr(route, f) for f in route.__dataclass_fields__}
    fields.update(changes)
    return Route(**fields)


def test_dropping_access_token_from_the_imports_forbidden_is_refused() -> None:
    """1.7: Core's REQUIRED_FORBIDDEN refuses the registration."""
    bad = _with(dw.SOURCES_HF_IMPORT, forbidden=MappingProxyType({"body.confirm_large": ANY}))
    with pytest.raises(ProgrammingError, match="access_token"):
        check_registration(bad)
    bad = _with(dw.SOURCES_HF_IMPORT, forbidden=MappingProxyType({"body.access_token": ANY}))
    with pytest.raises(ProgrammingError, match="confirm_large"):
        check_registration(bad)


def test_publish_checks_registration_needs_its_forbidden_repo_id() -> None:
    bad = Route(
        "midataworks.run_checks",
        "midataworks",
        "POST",
        "/api/v1/versions/{version_id}/publish-checks",
        GateClass.UNGATED_WRITE,
        "would run the checks",
        floor_entry="dataset.build_files",
    )
    with pytest.raises(ProgrammingError):
        RouteRegistry((bad,))


def test_build_version_registered_app_gated_is_refused_by_its_marker() -> None:
    """A19's control, as a test: 022's marker classifies POST /versions as a conditional gate."""
    from miassist.adapters.routes import classify_marker, when_tokens

    snap = json.loads(
        (Path(__file__).resolve().parents[2] / "fixtures/openapi/midataworks.json").read_text()
    )
    op = snap["paths"]["/api/v1/versions"]["post"]
    assert classify_marker("midataworks", "POST", "/api/v1/versions", op) is GateClass.UNGATED_WRITE
    assert when_tokens(op) == ROUTES.get("midataworks.build_version").gate_when


def test_marked_without_when_is_unknown() -> None:
    from miassist.adapters.routes import classify_marker

    with pytest.raises(UnknownGate):
        classify_marker("midataworks", "POST", "/api/v1/versions", {"x-approval-action": "x"})


def test_definition_copy_is_not_mutated() -> None:
    raw = json.loads(DEFINITION.read_text())
    assert copy.deepcopy(raw) == raw


def test_the_post_reads_say_they_only_compute() -> None:
    """003's ``computes_only`` (OVN-miassist-pb003-3): the three dry runs are marked, and a POST read
    without the mark is refused at registration."""
    assert {r.id for r in dw.DATASET_ROUTES if r.computes_only} == dw.POST_READS
    with pytest.raises(ProgrammingError, match="must say why"):
        check_registration(_with(dw.VERSIONS_PLAN, computes_only=False))
