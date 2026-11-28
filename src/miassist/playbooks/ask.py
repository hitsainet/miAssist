"""``ask()``: the choices a playbook step needs, asked the best way the client allows (001 FR-26,
AC-26.1 - AC-26.3; BR-G-11, M8; spike S-4).

Spike S-4 (2026-11-16): mcp 2.3.0 carries the 2026-07-28 multi-round-trip flow. A tool returns an
``InputRequiredResult`` holding one form ``ElicitRequest``; a client that declared form elicitation
answers it and the SDK retries the call with ``ctx.input_responses``. Under the handshake era
(2025-11-25 and older) the same result is "an invalid result", and a client that declared no
elicitation is refused. So ``ask`` sends the form only when the request is on a modern revision AND
the client declared form elicitation; otherwise it returns the teaching result: ``data.choices``
(each choice, its recommended value and the reason) and a ``next_steps`` entry repeating the call
with the recommendations filled in. Decline and cancel answer a calm result that changes nothing.
A choice never asks for a secret value; one marked as such (``is_secret_choice``) is refused when it
is defined.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from mcp.types import CallToolResult
from mcp_types import ElicitRequest, ElicitRequestFormParams, InputRequiredResult
from mcp_types.version import MODERN_PROTOCOL_VERSIONS

from miassist.adapters.base import ProgrammingError
from miassist.guidance.loader import Guidance
from miassist.results.build import build

REQUEST_KEY = "miassist_ask"
_NAME = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


@dataclass(frozen=True)
class Choice:
    """One choice: ``options`` (flat strings), a ``recommended`` one and the ``reason`` for it."""

    name: str
    title: str
    options: tuple[str, ...]
    recommended: str
    reason: str
    option_titles: tuple[str, ...] | None = None
    is_secret_choice: bool = False

    def __post_init__(self) -> None:
        if self.is_secret_choice:
            raise ProgrammingError(f"choice {self.name!r}: ask() never asks for a secret (FR-26)")
        if not _NAME.match(self.name):
            raise ProgrammingError(f"choice {self.name!r}: not an argument name")
        if self.recommended not in self.options:
            raise ProgrammingError(f"choice {self.name!r}: the recommendation is not an option")
        if self.option_titles is not None and len(self.option_titles) != len(self.options):
            raise ProgrammingError(f"choice {self.name!r}: one title per option")


@dataclass(frozen=True)
class Answered:
    """The person's choices, one value per choice, each one of its options."""

    values: dict[str, str]


def form_capable(ctx: Any) -> bool:
    """A modern-era request from a client that declared form elicitation."""
    if ctx is None or getattr(ctx, "protocol_version", None) not in MODERN_PROTOCOL_VERSIONS:
        return False
    caps = ctx.client_capabilities
    elicitation = getattr(caps, "elicitation", None) if caps is not None else None
    return getattr(elicitation, "form", None) is not None


def form_schema(choices: Sequence[Choice]) -> dict[str, Any]:
    """Flat primitive fields, titled enums, defaults = the recommendations."""
    properties: dict[str, Any] = {}
    for c in choices:
        titles = c.option_titles or c.options
        properties[c.name] = {
            "type": "string",
            "title": c.title,
            "description": c.reason,
            "oneOf": [{"const": o, "title": t} for o, t in zip(c.options, titles, strict=True)],
            "default": c.recommended,
        }
    return {"type": "object", "properties": properties, "required": [c.name for c in choices]}


def _answer(choices: Sequence[Choice], response: Any) -> Answered | None:
    content = getattr(response, "content", None)
    if getattr(response, "action", None) != "accept" or not isinstance(content, Mapping):
        return None
    values = {c.name: content.get(c.name) for c in choices}
    if all(
        isinstance(v, str) and v in c.options for c, v in zip(choices, values.values(), strict=True)
    ):
        return Answered({k: str(v) for k, v in values.items()})
    return None


async def ask(
    ctx: Any,
    guidance: Guidance,
    *,
    tool: str,
    args: Mapping[str, Any],
    choices: Sequence[Choice],
    level: str,
) -> Answered | CallToolResult | InputRequiredResult:
    """The answers if the person gave them; otherwise what the tool returns to ask for them."""
    if not choices:
        raise ProgrammingError("ask() needs at least one choice")
    responses = getattr(ctx, "input_responses", None) if ctx is not None else None
    if responses and REQUEST_KEY in responses:
        response = responses[REQUEST_KEY]
        answered = _answer(choices, response)
        if answered is not None:
            return answered
        return build(
            guidance,
            tool="ask",
            outcome="declined",
            level=level,
            data={"choices": [c.name for c in choices], "changed": False},
        )
    if form_capable(ctx):
        form = ElicitRequest(
            params=ElicitRequestFormParams(
                mode="form",
                message=guidance.why("ask_form"),
                requested_schema=form_schema(choices),
            )
        )
        return InputRequiredResult(input_requests={REQUEST_KEY: form})
    data = {
        "choices": [
            {
                "name": c.name,
                "title": c.title,
                "options": list(c.options),
                "recommended": c.recommended,
                "reason": c.reason,
            }
            for c in choices
        ]
    }
    filled = {**args, **{c.name: c.recommended for c in choices}}
    return build(
        guidance,
        tool="ask",
        outcome="choose",
        level=level,
        data=data,
        next_steps=[{"tool": tool, "args": filled, "why": guidance.why("ask_recommended")}],
    )
