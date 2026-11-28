"""Core tool behaviour: glossary, unavailable, strict arguments, annotations, prefix, health
(001 FTASKS 8.3, 9.2, 10.4, 10.7, 10.9, 10.10, 10.11)."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest
from mcp import Client

from miassist.guidance.loader import MARKER, Guidance
from miassist.server.specs import ToolSpec
from miassist.tools import all_specs
from tests.support.app_factory import FakeDatabase, client
from tests.support.fake_apps import all_fakes
from tests.support.servers import make_server, mark_reachable

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = json.loads((ROOT / "docs/schemas/mistudio-result-language-v1.json").read_text())
ALL = ("miworkbench", "miserver", "midataworks", "miforge")


def test_markers_resolve() -> None:
    guidance = Guidance()
    for where, text in guidance.all_texts():
        for key in MARKER.findall(text):
            assert key in guidance.glossary, (where, key)
    required = {
        "approval",
        "auroc",
        "calibration-bar",
        "checkpoint",
        "circuit",
        "cluster",
        "dataset-version",
        "detector",
        "evidence-ladder",
        "false-alarm",
        "feature",
        "gpu",
        "guidance-level",
        "held-out",
        "label-run",
        "out-of-distribution",
        "pack",
        "pooling-rule",
        "probe",
        "recipe",
        "rung",
        "sae",
        "served-model",
        "steering",
        "steering-strength",
    }
    assert required <= set(guidance.glossary)


def test_jargon_marked() -> None:
    guidance = Guidance()
    for where, text in guidance.all_texts():
        if where.startswith("glossary.yaml") or ".what_good" in where:
            continue
        unmarked = MARKER.sub("", text)
        for word in guidance.jargon:
            assert not re.search(rf"\b{re.escape(word)}\b", unmarked), (where, word)


async def test_resource_links_and_read() -> None:
    mcp, _deps = make_server(("miforge",), all_fakes())
    async with Client(mcp) as session:
        result = await session.call_tool("miassist_glossary", {"term": "AUROC"})
        links = [c for c in result.content if getattr(c, "type", "") == "resource_link"]
        assert [str(link.uri) for link in links] == ["miassist://glossary/auroc"]
        read = await session.read_resource("miassist://glossary/auroc")
        assert "AUROC" in read.contents[0].text


async def test_unknown_term() -> None:
    mcp, _ = make_server(("miforge",), all_fakes())
    async with Client(mcp) as session:
        result = await session.call_tool("miassist_glossary", {"term": "aurok"})
    assert result.is_error
    text = result.content[0].text
    assert text.startswith("unknown_term: ") and "auroc" in text and "\nfix: " in text


async def test_no_request_when_unreachable() -> None:
    fakes = all_fakes()
    mcp, deps = make_server(("miforge",), fakes)
    deps.runtime.detector.mark_unreachable("miforge", "connection refused")
    async with Client(mcp) as session:
        result = await session.call_tool("miassist_overview", {"app": "miforge"})
    assert result.is_error is False
    assert result.structured_content["unavailable"] == "miforge"
    assert result.structured_content["data"] is None
    assert fakes["miforge"].requests == []


async def test_unknown_argument() -> None:
    fakes = all_fakes()
    mcp, deps = make_server(("miforge",), fakes)
    await mark_reachable(deps)
    fakes["miforge"].requests.clear()
    async with Client(mcp) as session:
        result = await session.call_tool("miassist_overview", {"app": "miforge", "verbose": True})
    assert result.is_error
    assert "unknown_arguments" in result.content[0].text
    assert fakes["miforge"].requests == []


async def test_unknown_topic_lists_seven() -> None:
    mcp, _ = make_server((), all_fakes())
    async with Client(mcp) as session:
        result = await session.call_tool("miassist_guide", {"topic": "nope"})
    assert result.is_error
    for topic in ("start", "apps", "playbooks", "approvals", "results", "glossary", "connect"):
        assert topic in result.content[0].text


def rules() -> list[dict[str, Any]]:
    loaded: list[dict[str, Any]] = SCHEMA["x-annotation-rules"]
    return loaded


@pytest.mark.parametrize("rule", [r["id"] for r in SCHEMA["x-annotation-rules"]])
async def test_rules(rule: str) -> None:
    assert len(rules()) == 7
    mcp, _ = make_server(ALL, all_fakes())
    async with Client(mcp) as session:
        tools = {t.name: t for t in (await session.list_tools()).tools}
    specs = {s.name: s for s in all_specs()}
    for name, tool in tools.items():
        spec: ToolSpec = specs[name]
        hints = tool.annotations
        if rule == "AR-1":
            assert tool.title and hints.title
        elif rule == "AR-2":
            assert hints.read_only_hint is not None and hints.destructive_hint is not None
        elif rule == "AR-3":
            changes = bool(spec.effects & {"store_write", "store_delete", "app_write"})
            assert hints.read_only_hint is (not changes), name
        elif rule == "AR-4":
            assert hints.destructive_hint is ("store_delete" in spec.effects), name
        elif rule == "AR-5":
            assert hints.idempotent_hint is None and hints.open_world_hint is None
        elif rule == "AR-6":
            assert tool.output_schema is not None, f"{name}: untyped result (debt)"
        elif rule == "AR-7":
            assert not name.startswith("miassist_relay"), "Core has no relay"


async def test_tool_prefix() -> None:
    mcp, _ = make_server(ALL, all_fakes())
    async with Client(mcp) as session:
        names = [t.name for t in (await session.list_tools()).tools]
    assert names == sorted(names)
    for name in names:
        assert re.fullmatch(r"^miassist_[a-z0-9_]{1,55}$", name), name


def test_health_coarse() -> None:
    fakes = all_fakes()
    urls = {f"{a}_url": f"http://{a}.internal.example:8000" for a in ALL}
    transports = {a: f.transport() for a, f in fakes.items()}
    with client(transports=transports, apps="miforge,miserver", **urls) as test_client:
        body = test_client.get("/health").json()
    assert set(body) == {"status", "service", "version", "settings_store", "apps"}
    assert set(body["apps"]) == {"miforge", "miserver"}
    assert set(body["apps"].values()) <= {"reachable", "unreachable", "unknown"}
    text = json.dumps(body)
    assert "internal.example" not in text and "http" not in text


def test_db_stall() -> None:
    import time

    with client(database=FakeDatabase(stall_s=5.0)) as test_client:
        start = time.monotonic()
        body = test_client.get("/health").json()
    assert body["settings_store"] == "unavailable" and time.monotonic() - start < 1.5


async def test_overview_no_event_text() -> None:
    """miServer's probe status is shown as counts only, never event text (A14, FR-27)."""
    fakes = all_fakes()
    secret_prompt = "a stranger's prompt text test-only"
    fakes["miserver"].on("GET", "/api/models", {"data": []})
    fakes["miserver"].on("GET", "/api/clusters", {"data": []})
    fakes["miserver"].on(
        "GET",
        "/api/probes/status",
        {"data": {"armed": 2, "events_today": 5, "last_event": {"prompt": secret_prompt}}},
    )
    mcp, deps = make_server(("miserver",), fakes)
    await mark_reachable(deps)
    async with Client(mcp) as session:
        result = await session.call_tool("miassist_overview", {"app": "miserver"})
    probes = result.structured_content["data"]["lists"]["probes"]
    assert probes == {"counts": {"armed": 2, "events_today": 5}}
    assert secret_prompt not in json.dumps(result.structured_content)
    assert all(secret_prompt not in getattr(c, "text", "") for c in result.content)


async def test_extra_specs_registered_when_apps_installed() -> None:
    from miassist.guidance.loader import ToolText
    from miassist.server.specs import ToolSpec
    from miassist.tools import EXTRA_SPECS, core
    from tests.support.servers import guidance

    spec = ToolSpec(
        "miassist_fixture_extra",
        frozenset({"miforge"}),
        True,
        False,
        frozenset({"none"}),
        core.make_guide,
    )
    EXTRA_SPECS.append(spec)
    guidance().tools.tools["miassist_fixture_extra"] = ToolText(
        title="Fixture", description="Test only."
    )
    try:
        for installed, expected in ((("miforge",), True), (("miserver",), False)):
            mcp, _ = make_server(installed, all_fakes())
            async with Client(mcp) as session:
                names = {t.name for t in (await session.list_tools()).tools}
            assert ("miassist_fixture_extra" in names) is expected
    finally:
        EXTRA_SPECS.remove(spec)
        del guidance().tools.tools["miassist_fixture_extra"]
