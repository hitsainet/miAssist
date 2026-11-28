"""FR-5's calm absent answer (001 AC-5.3, US-3; FTASKS 11.7): asked for a playbook this
installation does not offer, the guide answers calmly: not an error, no ``unavailable``, none of
the alarm words, ``needs`` naming the missing apps, ``next_steps`` from the offered playbooks, and
the one sentence built by ``honest_end()``."""

from __future__ import annotations

import json
from typing import Any

import pytest
from mcp import Client

from miassist.results.honest_end import honest_end
from tests.support.fake_apps import all_fakes
from tests.support.servers import make_server

FORBIDDEN = ("error", "warning", "fail", "refus", "cannot", "unable")


async def ask_guide(installed: tuple[str, ...], playbook: str) -> Any:
    fakes = all_fakes()
    mcp, _ = make_server(installed, fakes)
    async with Client(mcp) as client:
        result = await client.call_tool("miassist_guide", {"playbook": playbook})
    assert all(f.requests == [] for f in fakes.values())
    return result


def words_of(result: Any) -> str:
    return " ".join(
        [json.dumps(result.structured_content)] + [getattr(c, "text", "") for c in result.content]
    ).lower()


@pytest.mark.parametrize("level", ["beginner"])
async def test_absent_playbook_is_calm(level: str) -> None:
    result = await ask_guide(("midataworks",), "start-miserver")
    assert result.is_error is False
    structured = result.structured_content
    assert "unavailable" not in structured
    data = structured["data"]
    assert data["offered"] is False and data["needs"] == ["miserver"]
    sentence = honest_end(["miserver"], ["midataworks"])
    assert data["honest_end"] == sentence
    assert (
        data["message"] == f"That playbook {sentence}. Here is what you can do with what you have:"
    )
    assert structured["next_steps"] == [
        {"tool": "miassist_dataset_find", "args": {}, "why": "Build, check and publish a dataset"},
        {
            "tool": "miassist_detector_start",
            "args": {},
            "why": "Build a behaviour detector",
        },
        {
            "tool": "miassist_overview",
            "args": {"app": "midataworks"},
            "why": "Start here: miDataworks",
        },
    ]
    for word in FORBIDDEN:
        assert word not in words_of(result), word


async def test_unknown_playbook_has_no_honest_end() -> None:
    result = await ask_guide(("miforge",), "no-such-playbook")
    data = result.structured_content["data"]
    assert result.is_error is False and data["needs"] == [] and "honest_end" not in data
    for word in FORBIDDEN:
        assert word not in words_of(result), word


async def test_empty_installation_points_at_the_guide() -> None:
    result = await ask_guide((), "start-miforge")
    data = result.structured_content["data"]
    assert data["needs"] == ["miforge"] and data["offered_playbooks"] == []
    assert result.structured_content["next_steps"][0]["tool"] == "miassist_guide"


async def test_offered_playbook_answers_its_entry() -> None:
    result = await ask_guide(("miforge",), "start-miforge")
    data = result.structured_content["data"]
    assert data["playbook"]["id"] == "start-miforge"
    assert data["playbook"]["first_step"] == {
        "tool": "miassist_overview",
        "args": {"app": "miforge"},
    }
    assert "offered" not in data
