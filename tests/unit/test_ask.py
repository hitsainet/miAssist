"""``ask()`` (001 FR-26, AC-26.1 - AC-26.3; FTASKS 11.6; spike S-4).

A fixture tool asks one choice through ``ask()`` and calls a fake app only once it has the answer.
A client on the 2026-07-28 revision that declared form elicitation gets the form (defaults = the
recommendations) and its answer reaches the tool; any other client gets the teaching result; a
decline or cancel changes nothing and calls no app; a secret choice cannot be defined.
"""

from __future__ import annotations

from typing import Any

import pytest
from mcp import Client
from mcp.server.mcpserver import Context, MCPServer
from mcp.types import CallToolResult
from mcp_types import ElicitResult

from miassist.adapters.base import ProgrammingError
from miassist.playbooks.ask import Answered, Choice, ask
from tests.support.servers import guidance

CHOICE = Choice(
    name="pooling",
    title="Pooling rule",
    options=("mean", "max"),
    option_titles=("Mean of the scores", "Highest score"),
    recommended="mean",
    reason="Mean is steadier on short texts.",
)


def fixture_server(app_calls: list[dict[str, str]]) -> MCPServer:
    server = MCPServer("ask-fixture")

    @server.tool()
    async def miassist_fixture_pick(ctx: Context[Any, Any], pooling: str | None = None) -> Any:
        if pooling is not None:
            app_calls.append({"pooling": pooling})
            return f"used {pooling}"
        answer = await ask(
            ctx,
            guidance(),
            tool="miassist_fixture_pick",
            args={},
            choices=[CHOICE],
            level="beginner",
        )
        if isinstance(answer, Answered):
            app_calls.append(answer.values)
            return f"used {answer.values['pooling']}"
        return answer

    return server


def callback(action: str, seen: list[Any]) -> Any:
    async def answer(context: Any, params: Any) -> ElicitResult:
        seen.append(params)
        if action == "accept":
            return ElicitResult(action="accept", content={"pooling": "max"})
        return ElicitResult(action=action)  # type: ignore[arg-type]

    return answer


async def test_form_when_capable() -> None:
    calls: list[dict[str, str]] = []
    seen: list[Any] = []
    async with Client(
        fixture_server(calls), mode="2026-07-28", elicitation_callback=callback("accept", seen)
    ) as client:
        result = await client.call_tool("miassist_fixture_pick", {})
    assert len(seen) == 1
    schema = seen[0].requested_schema
    field = schema["properties"]["pooling"]
    assert field["default"] == "mean" and field["type"] == "string"
    assert [o["const"] for o in field["oneOf"]] == ["mean", "max"]
    assert [o["title"] for o in field["oneOf"]] == ["Mean of the scores", "Highest score"]
    assert result.content[0].text == "used max"
    assert calls == [{"pooling": "max"}]


@pytest.mark.parametrize(
    "client_kwargs",
    [{"mode": "2026-07-28"}, {"mode": "legacy"}, {"mode": "legacy", "with_callback": True}],
    ids=["modern-no-elicitation", "handshake", "handshake-with-elicitation"],
)
async def test_teaching_otherwise(client_kwargs: dict[str, Any]) -> None:
    calls: list[dict[str, str]] = []
    seen: list[Any] = []
    kwargs = dict(client_kwargs)
    if kwargs.pop("with_callback", False):
        kwargs["elicitation_callback"] = callback("accept", seen)
    async with Client(fixture_server(calls), **kwargs) as client:
        result: CallToolResult = await client.call_tool("miassist_fixture_pick", {})
    assert seen == [] and calls == []
    assert result.is_error is False
    data = result.structured_content["data"]
    assert data["choices"] == [
        {
            "name": "pooling",
            "title": "Pooling rule",
            "options": ["mean", "max"],
            "recommended": "mean",
            "reason": "Mean is steadier on short texts.",
        }
    ]
    assert [(s["tool"], s["args"]) for s in result.structured_content["next_steps"]] == [
        ("miassist_fixture_pick", {"pooling": "mean"})
    ]


@pytest.mark.parametrize("action", ["decline", "cancel"])
async def test_decline_no_requests(action: str) -> None:
    calls: list[dict[str, str]] = []
    seen: list[Any] = []
    async with Client(
        fixture_server(calls), mode="2026-07-28", elicitation_callback=callback(action, seen)
    ) as client:
        result = await client.call_tool("miassist_fixture_pick", {})
    assert len(seen) == 1 and calls == []
    assert result.is_error is False
    assert result.structured_content["data"] == {"choices": ["pooling"], "changed": False}


def test_secret_choice_refused() -> None:
    with pytest.raises(ProgrammingError, match="never asks for a secret"):
        Choice("token", "Token", ("a",), "a", "x", is_secret_choice=True)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"name": "Bad-Name", "title": "t", "options": ("a",), "recommended": "a", "reason": "r"},
        {"name": "ok", "title": "t", "options": ("a",), "recommended": "b", "reason": "r"},
        {
            "name": "ok",
            "title": "t",
            "options": ("a", "b"),
            "recommended": "a",
            "reason": "r",
            "option_titles": ("A",),
        },
    ],
    ids=["name", "recommendation-not-an-option", "titles"],
)
def test_malformed_choice_refused(kwargs: dict[str, Any]) -> None:
    with pytest.raises(ProgrammingError):
        Choice(**kwargs)
