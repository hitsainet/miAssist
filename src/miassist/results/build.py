"""The one result builder (001 FR-12, FR-7, FR-9; FTID §3.6; spike S-2's path).

``build`` returns a ``CallToolResult`` whose ``structuredContent`` is an ``assist_result``:
``guidance``, ``data``, ``next_steps`` and, when present, ``approval`` and ``unavailable`` with its
``reason``. At beginner it renders ``explain`` from ``guidance/explain/<tool>.yaml[outcome]``; at
expert it omits it (the ONLY difference the level makes, FR-7). Every glossary term the explanation
marks, plus ``terms``, adds one ``resource_link`` block (``miassist://glossary/<key>``). The dict is
validated against ``AssistResult`` before it is returned.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

from mcp.types import CallToolResult, ResourceLink, TextContent

from miassist.contracts.result_language import AssistResult
from miassist.guidance.loader import Guidance

GLOSSARY_URI = "miassist://glossary/{key}"


def build(
    guidance: Guidance,
    *,
    tool: str,
    outcome: str,
    level: str,
    data: Any,
    next_steps: Sequence[Mapping[str, Any]] = (),
    approval: Mapping[str, Any] | None = None,
    unavailable: str | None = None,
    reason: str | None = None,
    terms: Sequence[str] = (),
    slots: Mapping[str, Any] | None = None,
) -> CallToolResult:
    result: dict[str, Any] = {
        "guidance": level,
        "data": data,
        "next_steps": [dict(step) for step in next_steps],
    }
    collected: list[str] = list(dict.fromkeys(terms))
    if level == "beginner":
        texts = guidance.explain[tool].outcomes[outcome]
        explain: dict[str, Any] = {}
        for field, text in texts.model_dump().items():
            rendered = guidance.render(text, dict(slots or {}))
            explain[field] = rendered.text
            collected += [t for t in rendered.terms if t not in collected]
        explain["terms"] = list(collected)
        result["explain"] = explain
    if approval is not None:
        result["approval"] = dict(approval)
    if unavailable is not None:
        result["unavailable"] = unavailable
        result["reason"] = reason or "unreachable"
    AssistResult.model_validate(result)
    links = [
        ResourceLink(
            type="resource_link",
            uri=GLOSSARY_URI.format(key=key),
            name=guidance.glossary[key].term,
        )
        for key in collected
        if key in guidance.glossary
    ]
    text = TextContent(type="text", text=json.dumps(result, sort_keys=True, default=str))
    return CallToolResult(content=[text, *links], structured_content=result, is_error=False)


def error_result(text: str) -> CallToolResult:
    """A tool error (``isError``) carrying the rendered error text (FR-17)."""
    return CallToolResult(content=[TextContent(type="text", text=text)], is_error=True)
