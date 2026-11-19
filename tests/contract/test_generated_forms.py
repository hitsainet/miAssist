"""The three generated forms of a playbook cannot drift (001 FR-5, AC-5.5, AC-5.8; FTASKS 11.1,
11.4): the guide entry ``miassist_guide`` serves, the prompt ``prompts/get`` serves and the skill
``resources/read`` serves each equal a fresh generation from the definition; editing the words one
step's ``explain_beginner`` key points at (in a temporary copy) changes all three with no other
edit; and no generated form ever carries a raw text key."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from mcp import Client
from scripts import write_skills

from miassist.guidance.loader import Guidance
from miassist.playbooks import generate
from tests.support.fake_apps import all_fakes
from tests.support.playbook_copies import copy_guidance, definition, write_definition
from tests.support.servers import make_server

ALL = ("miworkbench", "miserver", "midataworks", "miforge")
IDS = [f"start-{app}" for app in ALL] + ["detector-probe", "dataset", "steering"]  # 003-005


async def served_forms(words: Guidance | None = None) -> dict[str, tuple[str, str, str]]:
    mcp, _ = make_server(ALL, all_fakes(), words=words)
    out: dict[str, tuple[str, str, str]] = {}
    async with Client(mcp) as client:
        guide = await client.call_tool("miassist_guide", {"topic": "playbooks"})
        entries = {p["id"]: p["guide"] for p in guide.structured_content["data"]["playbooks"]}
        for playbook_id in IDS:
            prompt = await client.get_prompt(playbook_id, {})
            skill = await client.read_resource(f"miassist://skills/{playbook_id}")
            out[playbook_id] = (
                entries[playbook_id],
                prompt.messages[0].content.text,
                skill.contents[0].text,
            )
    return out


def generated(words: Guidance) -> dict[str, tuple[str, str, str]]:
    _, deps = make_server(ALL, all_fakes(), words=words)
    assert deps.playbooks is not None
    return {
        p.id: (
            generate.guide_entry(words, p, "beginner"),
            generate.prompt_text(words, p),
            generate.skill_markdown(words, p),
        )
        for p in deps.playbooks.offered
    }


async def test_three_forms_match_definition(tmp_path: Path) -> None:
    shipped = Guidance()
    original = await served_forms(shipped)
    assert original == generated(shipped)
    # edit the words one step's explain_beginner key points at, in a temporary copy
    root = copy_guidance(tmp_path)
    key = definition("start-miforge")["steps"][1]["explain_beginner"]
    words_file = root / "playbooks" / "start-miforge.yaml"
    text = words_file.read_text()
    marker = f'  {key}: "'
    assert text.count(marker) == 1
    words_file.write_text(text.replace(marker, f"{marker}Drift check. "))
    edited = Guidance(root)
    changed = await served_forms(edited)
    assert changed == generated(edited)
    for form in range(3):
        assert changed["start-miforge"][form] != original["start-miforge"][form], form
        assert "Drift check." in changed["start-miforge"][form]
    for other in IDS:
        if other != "start-miforge":
            assert changed[other] == original[other]


def _keys(data: dict[str, Any]) -> set[str]:
    keys = {data["title"], data["goal"]}
    for step in data["steps"]:
        keys |= {step["explain_beginner"], step["explain_expert"], step["done_when"]["description"]}
        if "title" in step:
            keys.add(step["title"])
    return keys


async def test_keys_resolve() -> None:
    forms = await served_forms()
    for playbook_id in IDS:
        keys = _keys(definition(playbook_id))
        assert all("." in k for k in keys), "keys must be distinctive to be searchable"
        for form in forms[playbook_id]:
            for key in keys:
                assert key not in form, (playbook_id, key)


def test_write_skills_writes_every_definition(tmp_path: Path) -> None:
    out = tmp_path / "skills"
    assert write_skills.main(["--out", str(out)]) == 0
    words = Guidance()
    for playbook_id in IDS:
        written = (out / playbook_id / "SKILL.md").read_text()
        _, deps = make_server(ALL, all_fakes())
        assert deps.playbooks is not None
        assert written == generate.skill_markdown(words, deps.playbooks.playbooks[playbook_id])


def test_write_skills_refuses_a_missing_key(tmp_path: Path) -> None:
    folder = tmp_path / "definitions"
    folder.mkdir()
    data = definition("start-miforge")
    data["steps"][0]["explain_expert"] = "look-around.nowhere"
    write_definition(folder, data)
    with pytest.raises(SystemExit) as refused:
        write_skills.main(["--out", str(tmp_path / "skills"), "--definitions", str(folder)])
    assert refused.value.code not in (0, None)
    assert "look-around.nowhere" in str(refused.value.code)
    assert not (tmp_path / "skills").exists()


def test_skill_names_the_playbook() -> None:
    forms = generated(Guidance())
    for playbook_id, (_, _, skill) in forms.items():
        head = skill.split("---")[1]
        assert f"name: {playbook_id}" in head
        assert json.dumps(skill)  # one string, newline-terminated
        assert skill.endswith("\n") and not skill.endswith("\n\n")
