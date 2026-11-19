"""The live registration of the five tools, the prompt and the playbook (FPRD FR-003.3;
FTASKS 1.3, 1.6). Reads the LIVE ``tools/list`` and ``prompts/list`` of a server built with every
app installed; the removal controls are recorded in ``0xcc/reviews/003_mutations.md``."""

from __future__ import annotations

import pytest
from mcp import Client

from miassist.playbooks.status import PROVIDERS
from tests.support.fake_apps import all_fakes
from tests.support.servers import make_server

ALL = ("miworkbench", "miserver", "midataworks", "miforge")
EXPECTED = {
    "miassist_detector_start": (
        "Detector: describe the behaviour",
        {
            "description",
            "key",
            "positive_meaning",
            "negative_meaning",
            "target_false_alarm_rate",
            "adopt_existing",
            "confirm",
        },
    ),
    "miassist_detector_data": (
        "Detector: get labelled data",
        {
            "key",
            "route",
            "hf_repo",
            "config",
            "split_train",
            "split_test",
            "split_calibration",
            "text_column",
            "label_column",
            "positive_values",
            "ood_hf_repo",
            "ood_split",
            "ood_text_column",
            "ood_label_column",
            "ood_positive_values",
            "everyday_view",
            "nonsense_view",
            "visibility",
            "ask_again",  # the send (Confirmation fix C-int-1, 2026-11-16)
            "confirm",
        },
    ),
    "miassist_detector_train": (
        "Detector: train it",
        {"key", "model", "approval_id", "expert_config", "ask_again", "confirm"},
    ),
    "miassist_detector_verdict": (
        "Detector: get the verdict",
        {"key", "probe", "approval_id", "ask_again", "confirm"},
    ),
    "miassist_detector_deploy": (
        "Detector: deploy it",
        {"key", "probe", "hub_repo", "below_rung2_reason", "approval_id", "ask_again", "confirm"},
    ),
}


async def test_live_tools_list() -> None:
    mcp, _ = make_server(ALL, all_fakes())
    async with Client(mcp) as client:
        tools = {t.name: t for t in (await client.list_tools()).tools}
    for name, (title, params) in EXPECTED.items():
        assert name in tools, name
        tool = tools[name]
        assert tool.title == title and tool.annotations.title == title
        assert tool.annotations.read_only_hint is False, name
        assert tool.annotations.destructive_hint is False, name
        assert tool.annotations.idempotent_hint is None and tool.annotations.open_world_hint is None
        assert set(tool.input_schema["properties"]) == params, name
        assert tool.output_schema is not None, name


async def test_route_enum_lists_installed_routes_only() -> None:
    for installed, expected in (
        (ALL, ["my_labelled_data", "build_with_midataworks"]),
        (("miworkbench",), ["my_labelled_data"]),
        (("midataworks",), ["build_with_midataworks"]),
    ):
        mcp, _ = make_server(installed, all_fakes())
        async with Client(mcp) as client:
            tool = next(
                t for t in (await client.list_tools()).tools if t.name == "miassist_detector_data"
            )
        schema = tool.input_schema["properties"]["route"]
        branches = schema.get("anyOf", [schema])
        values = [v for b in branches for v in b.get("enum", [b["const"]] if "const" in b else [])]
        assert values == expected, installed


async def test_live_prompts_list() -> None:
    mcp, _ = make_server(ALL, all_fakes())
    async with Client(mcp) as client:
        prompts = {p.name: p for p in (await client.list_prompts()).prompts}
    assert prompts["detector-probe"].title == "Build a behaviour detector"
    assert prompts["detector-probe"].arguments in (None, [])


@pytest.mark.parametrize(
    "installed,tools",
    [
        (("miforge",), set()),
        (("miworkbench",), {"start", "data", "train", "verdict"}),
        (("midataworks",), {"start", "data"}),
        (("miserver",), {"deploy"}),
    ],
)
async def test_offered_by_apps(installed: tuple[str, ...], tools: set[str]) -> None:
    mcp, _ = make_server(installed, all_fakes())
    async with Client(mcp) as client:
        names = {t.name for t in (await client.list_tools()).tools}
        prompts = {p.name for p in (await client.list_prompts()).prompts}
    assert {n.removeprefix("miassist_detector_") for n in names if "detector" in n} == tools
    assert ("detector-probe" in prompts) is bool(tools)


def test_status_provider_registered() -> None:
    assert "detector-probe" in PROVIDERS
