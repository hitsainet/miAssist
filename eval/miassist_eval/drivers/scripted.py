"""Tier 1a: the scripted client (FR-002.16; FTID §3.12). A plain MCP client (the official ``mcp``
SDK ``Client``), no model. The baseline path comes from ``baseline_paths.yaml``; the miAssist path
from the shipped playbook definition, checked against the live ``prompts/list`` and ``tools/list``
(activates as 003-005 ship their definitions; until then the miAssist cell is NOT RUN)."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, ClassVar

import yaml

from miassist_eval.drivers.base import ClientInfo, Driver

EVAL_ROOT = Path(__file__).resolve().parents[2]
BASELINE_PATHS = EVAL_ROOT / "baseline_paths.yaml"
DEFINITIONS = EVAL_ROOT.parent / "src" / "miassist" / "playbooks" / "definitions"


@dataclass
class Step:
    tool: str
    arguments: dict[str, Any] = field(default_factory=dict)


def baseline_path(goal_id: str, path: Path = BASELINE_PATHS) -> list[Step]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    steps = (data.get("goals") or {}).get(goal_id, {}).get("steps", [])
    return [Step(str(s["tool"]), dict(s.get("arguments") or {})) for s in steps]


def definition_path(playbook_id: str, directory: Path = DEFINITIONS) -> list[Step] | None:
    """A shipped playbook definition's steps (read as data), or None when not shipped."""
    path = directory / f"{playbook_id}.json"
    if not path.is_file():
        return None
    doc = json.loads(path.read_text(encoding="utf-8"))
    return [Step(str(s["tool"]), dict(s.get("arguments") or {})) for s in doc.get("steps", [])]


def missing_tools(steps: Sequence[Step], live_tools: Sequence[str]) -> list[str]:
    return [s.tool for s in steps if s.tool not in set(live_tools)]


class ScriptedDriver(Driver):
    name: ClassVar[str] = "scripted"
    paid: ClassVar[bool] = False

    def preflight(self, cfg: dict[str, Any]) -> ClientInfo:
        import importlib.metadata

        return ClientInfo(
            name=self.name,
            version=importlib.metadata.version("mcp"),
            model_requested=None,
            model_served=None,
        )

    async def run(
        self, url: str, steps: Sequence[Step], headers: Mapping[str, str] | None = None
    ) -> dict[str, Any]:
        """List the tools, then call each step in order through ``url`` (the tap)."""
        from mcp import Client

        transcript: dict[str, Any] = {"tools": [], "calls": []}
        async with Client(url) as client:
            listed = await client.list_tools()
            transcript["tools"] = [t.name for t in listed.tools]
            for step in steps:
                result = await client.call_tool(step.tool, step.arguments)
                text = "".join(getattr(c, "text", "") for c in result.content)
                transcript["calls"].append(
                    {
                        "tool": step.tool,
                        "arguments": step.arguments,
                        "is_error": bool(result.is_error),
                        "text": text,
                        "structured": result.structured_content,
                    }
                )
        return transcript
