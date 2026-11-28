"""The three generated forms of a playbook (001 FR-5, AC-5.5, AC-5.8; BR-G-9; FTID §3.8).

Pure functions of a resolved definition and the guidance templates
(``guidance/playbook_forms.yaml``): the guide entry (``miassist_guide``), the MCP prompt (named by
the playbook id) and the skill (``SKILL.md``, written by ``scripts/write_skills.py`` and served as
``miassist://skills/<id>``). Nothing caches their output: each call renders from the definition,
so editing a playbook's words changes all three and nothing else can.
"""

from __future__ import annotations

import json
from typing import Any, Literal

from miassist.guidance.loader import Guidance
from miassist.playbooks.registry import ResolvedPlaybook

Level = Literal["beginner", "expert"]
SKILL_URI = "miassist://skills/{id}"


def _steps(guidance: Guidance, playbook: ResolvedPlaybook, level: Level) -> str:
    forms = guidance.playbook_forms
    lines = []
    for n, step in enumerate(playbook.steps, start=1):
        if step.skipped:
            lines.append(guidance.render(forms.step_skipped, {"n": n, "title": step.title}).text)
            continue
        args = f" {json.dumps(dict(step.args), sort_keys=True)}" if step.args else ""
        explain = step.explain_beginner if level == "beginner" else step.explain_expert
        slots = {"n": n, "title": step.title, "tool": step.tool, "args": args, "explain": explain}
        lines.append(guidance.render(forms.step_line, slots).text)
    return "\n".join(lines)


def _slots(guidance: Guidance, playbook: ResolvedPlaybook, level: Level) -> dict[str, object]:
    return {
        "id": playbook.id,
        "version": playbook.version,
        "title": playbook.title,
        "goal": playbook.goal,
        "steps": _steps(guidance, playbook, level),
    }


def guide_entry(guidance: Guidance, playbook: ResolvedPlaybook, level: Level) -> str:
    """The playbook's entry in ``miassist_guide`` at ``level``."""
    return guidance.render(
        guidance.playbook_forms.guide_entry, _slots(guidance, playbook, level)
    ).text


def prompt_text(guidance: Guidance, playbook: ResolvedPlaybook) -> str:
    """The one user message of the playbook's MCP prompt (beginner explanations)."""
    return guidance.render(
        guidance.playbook_forms.prompt, _slots(guidance, playbook, "beginner")
    ).text


def skill_markdown(guidance: Guidance, playbook: ResolvedPlaybook) -> str:
    """The playbook's ``SKILL.md`` (beginner explanations), ending in one newline."""
    text = guidance.render(
        guidance.playbook_forms.skill, _slots(guidance, playbook, "beginner")
    ).text
    return text.rstrip("\n") + "\n"


def listing(guidance: Guidance, playbook: ResolvedPlaybook, level: Level) -> dict[str, Any]:
    """The playbook as ``miassist_guide`` lists it: id, title, goal, first step, guide entry."""
    first = playbook.first_step
    return {
        "id": playbook.id,
        "version": playbook.version,
        "title": playbook.title,
        "goal": playbook.goal,
        "first_step": {"tool": first.tool, "args": dict(first.args)},
        "guide": guide_entry(guidance, playbook, level),
    }
