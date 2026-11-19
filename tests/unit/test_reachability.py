"""Every Core tool is in the live registry with its title, hints and input schema, and a call makes
exactly its app requests (001 FTASKS 8.4, 10.3; ADR-011 item 1). Deleting a registration turns its
test red (recorded per tool)."""

from __future__ import annotations

from typing import Any

import pytest
from mcp import Client

from miassist.tools import EXTRA_SPECS, all_specs
from tests.support.fake_apps import FakeApp, all_fakes
from tests.support.servers import make_server, mark_reachable

ALL = ("miworkbench", "miserver", "midataworks", "miforge")
CORE = {
    "miassist_approval_status": (True, False),
    "miassist_glossary": (True, False),
    "miassist_guide": (True, False),
    "miassist_overview": (True, False),
    "miassist_reset_my_settings": (False, True),
    "miassist_set_guidance": (False, False),
    "miassist_status": (True, False),
}


DATASET_TOOLS = {
    "miassist_dataset_find",
    "miassist_dataset_build",
    "miassist_dataset_check",
    "miassist_dataset_publish",
}


async def tools_of(installed: tuple[str, ...]) -> dict[str, Any]:
    mcp, _ = make_server(installed, all_fakes())
    async with Client(mcp) as client:
        return {t.name: t for t in (await client.list_tools()).tools}


async def test_registry_has_every_core_tool() -> None:
    tools = await tools_of(ALL)
    # Core's seven, plus exactly the playbook chains' registered specs (003: five detector tools,
    # all_specs(); 004: four dataset tools, EXTRA_SPECS).
    assert set(tools) == {s.name for s in all_specs()}
    assert set(CORE) <= set(tools)
    assert {s.name for s in EXTRA_SPECS} >= DATASET_TOOLS
    for name, (read_only, destructive) in CORE.items():
        tool = tools[name]
        assert tool.title, name
        assert tool.annotations.read_only_hint is read_only, name
        assert tool.annotations.destructive_hint is destructive, name
        assert tool.annotations.idempotent_hint is None and tool.annotations.open_world_hint is None
        assert tool.input_schema.get("additionalProperties") is False, name


async def call(
    installed: tuple[str, ...],
    tool: str,
    args: dict[str, Any],
    fakes: dict[str, FakeApp] | None = None,
) -> tuple[Any, dict[str, FakeApp]]:
    fakes = fakes or all_fakes()
    mcp, deps = make_server(installed, fakes)
    await mark_reachable(deps)
    for fake in fakes.values():
        fake.requests.clear()
    async with Client(mcp) as client:
        result = await client.call_tool(tool, args)
    return result, fakes


@pytest.mark.parametrize(
    "tool",
    [
        "miassist_guide",
        "miassist_glossary",
        "miassist_status",
        "miassist_set_guidance",
        "miassist_reset_my_settings",
    ],
)
async def test_app_independent_tools_make_no_request(tool: str) -> None:
    args: dict[str, Any] = {"level": "expert"} if tool == "miassist_set_guidance" else {}
    result, fakes = await call(ALL, tool, args)
    assert not result.is_error, result.content
    assert all(f.requests == [] for f in fakes.values())


async def test_guide_registered_and_answers() -> None:
    result, fakes = await call(("miforge",), "miassist_guide", {})
    data = result.structured_content["data"]
    assert [a["app"] for a in data["installed"]] == ["miforge"]
    assert all(f.requests == [] for f in fakes.values())


async def test_overview_calls_miforge() -> None:
    fakes = all_fakes()
    fakes["miforge"].on("GET", "/api/v1/runs", {"runs": [{"name": "r1"}], "total": 1})
    fakes["miforge"].on("GET", "/api/v1/packs", [{"name": "p1"}])
    fakes["miforge"].on("GET", "/api/v1/checkpoints", {"items": []})
    result, fakes = await call(("miforge",), "miassist_overview", {"app": "miforge"}, fakes)
    assert not result.is_error, result.content
    reads = [(r.method, r.path, r.params) for r in fakes["miforge"].requests]
    assert reads == [
        ("GET", "/api/v1/runs", {"limit": "3", "offset": "0"}),
        ("GET", "/api/v1/packs", {}),
        ("GET", "/api/v1/checkpoints", {"limit": "3"}),
    ]
    lists = result.structured_content["data"]["lists"]
    assert lists["runs"] == {"count": 1, "at_least": False, "newest": ["r1"]}


async def test_approval_status_reads_once() -> None:
    fakes = all_fakes()
    fakes["midataworks"].on(
        "GET",
        "/api/v1/approvals/{approval_id}",
        {"id": "ap1", "status": "executing", "action": "build"},
    )
    result, fakes = await call(
        ("midataworks",),
        "miassist_approval_status",
        {"app": "midataworks", "approval_id": "ap1"},
        fakes,
    )
    assert not result.is_error, result.content
    assert [(r.method, r.path) for r in fakes["midataworks"].requests] == [
        ("GET", "/api/v1/approvals/ap1")
    ]
    approval = result.structured_content["approval"]
    assert approval["status"] == "executing" and approval["then"] == "server_runs"


async def test_instructions_served() -> None:
    mcp, _ = make_server(ALL, all_fakes())
    async with Client(mcp) as client:
        instructions = client.instructions
    assert mcp.instructions and "miassist_guide" in mcp.instructions
    assert len(mcp.instructions) < 4096
    head = mcp.instructions[:512]
    for needle in ("miassist_guide", "approval", "unavailable", "cannot approve"):
        assert needle in head, needle
    assert instructions == mcp.instructions


def fprd_table() -> dict[str, tuple[str, bool, bool, str]]:
    """FPRD §4's Core tool table, read from the document itself (AC-18.2)."""
    from tests.support.source_tree import source_only

    doc = source_only("0xcc/prds/001_FPRD|Core.md").read_text()
    section = doc[doc.index("## 4. User Experience Requirements") : doc.index("## 5. ")]
    rows: dict[str, tuple[str, bool, bool, str]] = {}
    for line in section.splitlines():
        if line.startswith("| `miassist_"):
            cells = [c.strip() for c in line.strip("|").split("|")]
            rows[cells[0].strip("`")] = (cells[1], cells[2] == "true", cells[3] == "true", cells[4])
    return rows


async def test_table_matches_registry() -> None:
    table = fprd_table()
    assert set(table) == set(CORE)
    tools = await tools_of(ALL)
    empty = await tools_of(())
    for name, (title, read_only, destructive, requires) in table.items():
        tool = tools[name]
        assert tool.title == title and tool.annotations.title == title, name
        assert tool.annotations.read_only_hint is read_only, name
        assert tool.annotations.destructive_hint is destructive, name
        assert (name in empty) is (requires == "none"), name


async def test_registry_loaded() -> None:
    """AC-5.4: the live registry is populated at start from the definitions directory."""
    import json
    from pathlib import Path

    folder = Path(__file__).resolve().parents[2] / "src/miassist/playbooks/definitions"
    shipped = {
        (d["id"], d["version"])
        for d in (json.loads(p.read_text()) for p in sorted(folder.glob("*.json")))
    }
    assert (
        len(shipped) == 7
    )  # four start-here playbooks, 003's detector-probe, 004's dataset, 005's steering
    _, deps = make_server(ALL, all_fakes())
    assert deps.playbooks is not None
    live = {(p.id, p.version) for p in deps.playbooks.playbooks.values()}
    assert live == shipped


@pytest.mark.parametrize(
    "installed",
    [(), ("miforge",), ("miserver", "midataworks"), ALL],
    ids=["empty", "miforge", "miserver+midataworks", "all"],
)
async def test_prompt_per_offered_playbook(installed: tuple[str, ...]) -> None:
    """AC-5.6: exactly one prompt per offered playbook, named by its id; none for the others."""
    mcp, _ = make_server(installed, all_fakes())
    async with Client(mcp) as client:
        names = [p.name for p in (await client.list_prompts()).prompts]
        expected = [f"start-{app}" for app in installed]
        if {"miworkbench", "miserver", "midataworks"} & set(installed):
            expected.append("detector-probe")
        expected += ["dataset"] if "midataworks" in installed else []
        expected += ["steering"] if {"miworkbench", "miserver"} & set(installed) else []
        assert sorted(names) == sorted(expected)
        for name in names:
            prompt = await client.get_prompt(name, {})
            assert prompt.messages and name in prompt.messages[0].content.text


async def test_skill_resource_only_for_offered() -> None:
    mcp, _ = make_server(("miforge",), all_fakes())
    async with Client(mcp) as client:
        read = await client.read_resource("miassist://skills/start-miforge")
        assert read.contents[0].text.startswith("---\nname: start-miforge\n")
        with pytest.raises(Exception, match="start-miserver"):
            await client.read_resource("miassist://skills/start-miserver")
