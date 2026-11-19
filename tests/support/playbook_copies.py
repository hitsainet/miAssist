"""Temporary copies of the shipped guidance and playbook definitions, for the refusal, drift and
dispatch tests (001 FTASKS 11.x). Nothing here writes inside the package."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
GUIDANCE = ROOT / "src/miassist/guidance"
DEFINITIONS = ROOT / "src/miassist/playbooks/definitions"


def copy_guidance(tmp: Path) -> Path:
    target = tmp / "guidance"
    shutil.copytree(GUIDANCE, target, ignore=shutil.ignore_patterns("__pycache__", "*.py"))
    return target


def copy_definitions(tmp: Path) -> Path:
    target = tmp / "definitions"
    shutil.copytree(DEFINITIONS, target)
    return target


def definition(playbook_id: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((DEFINITIONS / f"{playbook_id}.json").read_text())
    return data


def write_definition(folder: Path, data: dict[str, Any], name: str | None = None) -> Path:
    path = folder / (name or f"{data['id']}.json")
    path.write_text(json.dumps(data, indent=2) + "\n")
    return path


def write_words(guidance_root: Path, playbook_id: str, texts: dict[str, str]) -> Path:
    path = guidance_root / "playbooks" / f"{playbook_id}.yaml"
    lines = ["version: 1", "texts:"] + [f"  {k}: {json.dumps(v)}" for k, v in texts.items()]
    path.write_text("\n".join(lines) + "\n")
    return path


FIXTURE_WORDS = {
    "playbook.title": "Fixture playbook",
    "playbook.goal": "A fixture goal for the tests.",
    "one.title": "Step one",
    "one.beginner": "The first step, explained for a beginner.",
    "one.expert": "First step.",
    "one.done": "The first step is done.",
    "two.title": "Step two",
    "two.beginner": "The second step, explained for a beginner.",
    "two.expert": "Second step.",
    "two.done": "The second step is done.",
}


def fixture_definition(
    playbook_id: str = "fixture-pb",
    requires: list[str] | None = None,
    steps: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    def step(sid: str, tool: str, args: dict[str, Any], **extra: Any) -> dict[str, Any]:
        return {
            "id": sid,
            "title": f"{sid}.title",
            "tool": tool,
            "args": args,
            "explain_beginner": f"{sid}.beginner",
            "explain_expert": f"{sid}.expert",
            "done_when": {"description": f"{sid}.done", "pointer": "/entries", "op": "exists"},
            **extra,
        }

    return {
        "kind": "mistudio.playbook/v1",
        "id": playbook_id,
        "version": 2,
        "title": "playbook.title",
        "goal": "playbook.goal",
        "requires_apps": requires or ["miforge"],
        "steps": steps
        or [
            step("one", "miassist_glossary", {}, entry=True),
            step("two", "miassist_guide", {"topic": "playbooks"}),
        ],
    }
