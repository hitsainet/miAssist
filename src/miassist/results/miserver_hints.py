"""miServer's next-tool hints, mapped (001 FR-25; BR-A-1). miServer names its own tools in a
result's ``next``; miAssist never passes another server's tool names on (FR-19), so each hint maps to
a miAssist tool or to plain words from ``guidance/miserver_next.yaml``."""

from __future__ import annotations

from importlib import resources
from typing import Any

import yaml


def load_hints() -> dict[str, dict[str, Any]]:
    raw = resources.files("miassist.guidance").joinpath("miserver_next.yaml").read_text()
    data: dict[str, Any] = yaml.safe_load(raw)
    hints: dict[str, dict[str, Any]] = data["hints"]
    return hints


def next_from_hint(
    name: str, hints: dict[str, dict[str, Any]] | None = None
) -> dict[str, Any] | str:
    """A ``next_step`` (when the hint maps to a miAssist tool) or the plain words; unknown -> ""."""
    table = hints if hints is not None else load_hints()
    entry = table.get(name)
    if entry is None:
        return ""
    if "tool" in entry:
        return {"tool": entry["tool"], "args": dict(entry.get("args", {})), "why": entry["words"]}
    return str(entry["words"])
