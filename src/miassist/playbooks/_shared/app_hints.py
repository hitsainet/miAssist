"""App hints to miAssist next steps (003 FTID §12; FPRD §6; A6).

Apps name their own MCP tools in hints: the A6 ``next_steps`` list when an app sends it, else the
legacy ``next`` (miWorkbench ``{tool, arguments, why}``, miDataworks ``{tool, args, why}``, miServer
a tool name in ``error.next``). miAssist never forwards them: each name is mapped through
``guidance/playbook_hints.yaml`` to a miAssist tool, and an unmapped name becomes a plain sentence
(``{"say": ...}``) the result can show, never a call.
"""

from __future__ import annotations

from collections.abc import Mapping
from functools import cache
from importlib import resources
from typing import Any

import yaml


@cache
def table() -> dict[str, dict[str, str]]:
    raw = yaml.safe_load(
        resources.files("miassist.guidance").joinpath("playbook_hints.yaml").read_text("utf-8")
    )
    return {str(k): dict(v) for k, v in raw["hints"].items()}


def raw_hints(body: Any) -> list[dict[str, Any]]:
    """The app's hint entries: ``next_steps`` first, then legacy ``next`` / ``error.next``."""
    if not isinstance(body, Mapping):
        return []
    found: Any = body.get("next_steps")
    if found is None:
        found = body.get("next")
    if found is None and isinstance(body.get("error"), Mapping):
        found = body["error"].get("next")
    if found is None and isinstance(body.get("detail"), Mapping):
        found = body["detail"].get("next")
    items = found if isinstance(found, list) else [found] if found else []
    out = []
    for item in items:
        if isinstance(item, str):
            out.append({"tool": item})
        elif isinstance(item, Mapping) and isinstance(item.get("tool"), str):
            out.append(dict(item))
    return out


def next_steps_of(body: Any, args: Mapping[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
    """``(miAssist next steps, plain sentences)`` for an app answer. ``args`` are the journey's
    own arguments (the key); app arguments are never copied."""
    steps: list[dict[str, Any]] = []
    said: list[str] = []
    for hint in raw_hints(body):
        mapped = table().get(hint["tool"])
        if mapped is None:
            said.append(hint["tool"].replace("_", " "))
            continue
        step = {"tool": mapped["tool"], "args": dict(args), "why": mapped["why"]}
        if step not in steps:
            steps.append(step)
    return steps, said
