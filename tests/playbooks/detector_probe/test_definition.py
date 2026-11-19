"""The definition, its words and the generated forms (FPRD FR-003.1, FR-003.2; FTASKS 1.1, 1.2, 1.7)."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from mcp import Client

from miassist.contracts.playbook import Playbook
from miassist.guidance.loader import Guidance
from miassist.playbooks import generate
from miassist.playbooks.registry import PlaybookError, load
from miassist.tools import all_specs
from tests.support.fake_apps import all_fakes
from tests.support.servers import make_server

ROOT = Path(__file__).resolve().parents[3]
DEFINITION = ROOT / "src/miassist/playbooks/definitions/detector-probe.json"
TOOLS = frozenset(s.name for s in all_specs())
ALL = ("miworkbench", "miserver", "midataworks", "miforge")
REQUIRED = ("kind", "version", "id", "title", "goal", "requires_apps", "steps")
STEP_REQUIRED = ("id", "tool", "explain_beginner", "explain_expert", "done_when")


def raw() -> dict:  # type: ignore[type-arg]
    return json.loads(DEFINITION.read_text())


def test_definition_validates_and_matches_ftid() -> None:
    playbook = Playbook.model_validate(raw())
    assert playbook.id == "detector-probe" and playbook.version == 1
    assert [s.id for s in playbook.steps] == ["describe", "data", "train", "verdict", "deploy"]
    assert [s.tool.root for s in playbook.steps] == [
        "miassist_detector_start",
        "miassist_detector_data",
        "miassist_detector_train",
        "miassist_detector_verdict",
        "miassist_detector_deploy",
    ]
    assert [s.id for s in playbook.steps if s.entry] == ["describe", "deploy"]


@pytest.mark.parametrize("field", REQUIRED)
def test_removing_a_required_field_names_it(field: str, tmp_path: Path) -> None:
    doc = raw()
    del doc[field]
    folder = tmp_path / "definitions"
    folder.mkdir()
    (folder / "detector-probe.json").write_text(json.dumps(doc))
    with pytest.raises(PlaybookError, match=field):
        load(Guidance(), ALL, TOOLS, folder)


@pytest.mark.parametrize("field", STEP_REQUIRED)
def test_removing_a_required_step_field_names_it(field: str, tmp_path: Path) -> None:
    doc = raw()
    del doc["steps"][2][field]
    folder = tmp_path / "definitions"
    folder.mkdir()
    (folder / "detector-probe.json").write_text(json.dumps(doc))
    with pytest.raises(PlaybookError, match=f"steps.2.{field}" if field != "id" else "steps.2"):
        load(Guidance(), ALL, TOOLS, folder)


def test_every_key_resolves() -> None:
    registry = load(Guidance(), ALL, TOOLS)
    resolved = registry.playbooks["detector-probe"]
    assert resolved.title == "Build a behaviour detector"
    assert all(s.explain_beginner and s.done_description for s in resolved.steps)
    assert {"rung", "detector", "view"} <= set(resolved.terms)


def copy_guidance(tmp_path: Path) -> Path:
    root = tmp_path / "guidance"
    shutil.copytree(ROOT / "src/miassist/guidance", root)
    return root


def test_negative_control_missing_key_fails_the_build(tmp_path: Path) -> None:
    root = copy_guidance(tmp_path)
    words = root / "playbooks/detector-probe.yaml"
    text = words.read_text()
    words.write_text(text.replace("  detector.train.done:", "  detector.train.gone:"))
    with pytest.raises(PlaybookError, match=r"detector\.train\.done"):
        load(Guidance(root), ALL, TOOLS)


async def forms(words: Guidance) -> tuple[str, str, str]:
    mcp, _ = make_server(ALL, all_fakes(), words=words)
    async with Client(mcp) as client:
        guide = await client.call_tool("miassist_guide", {"topic": "playbooks"})
        entry = next(
            p["guide"]
            for p in guide.structured_content["data"]["playbooks"]
            if p["id"] == "detector-probe"
        )
        prompt = (await client.get_prompt("detector-probe", {})).messages[0].content.text
        skill = (await client.read_resource("miassist://skills/detector-probe")).contents[0].text
    return entry, prompt, skill


async def test_generated_forms_equal_a_fresh_generation(tmp_path: Path) -> None:
    shipped = Guidance()
    served = await forms(shipped)
    resolved = load(shipped, ALL, TOOLS).playbooks["detector-probe"]
    assert served == (
        generate.guide_entry(shipped, resolved, "beginner"),
        generate.prompt_text(shipped, resolved),
        generate.skill_markdown(shipped, resolved),
    )
    # negative control: edit one explain_beginner key's words without regenerating anything
    root = copy_guidance(tmp_path)
    words = root / "playbooks/detector-probe.yaml"
    marker = '  detector.verdict.beginner: "'
    assert words.read_text().count(marker) == 1
    words.write_text(words.read_text().replace(marker, f"{marker}Drift check. "))
    changed = await forms(Guidance(root))
    for before, after in zip(served, changed, strict=True):
        assert before != after and "Drift check." in after
