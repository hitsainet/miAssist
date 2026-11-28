"""miAssist's error type (PADR ADR-013; Foundation task 2.3).

A ``MiAssistError`` carries a machine code, a one-line message, the fix a person can make and the
next steps. Codes match ``ERROR_CODE_PATTERN`` (A30): lower case, one optional dotted app prefix,
at most 64 characters. The text rendering of ``mistudio.result-language/v1`` errors is feature 001's
(FR-17) and lives beside this class once 001 lands.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from typing import Any, Final

#: The one error-code pattern (CHAIN_PLAN A30). ``contracts`` embeds the same string.
ERROR_CODE_PATTERN: Final = r"^[a-z][a-z0-9_]*(\.[a-z0-9_]+)?$"
ERROR_CODE_MAX: Final = 64
_CODE = re.compile(ERROR_CODE_PATTERN)


def valid_code(code: str) -> bool:
    """True when ``code`` is a well-formed error code."""
    return len(code) <= ERROR_CODE_MAX and _CODE.fullmatch(code) is not None


class MiAssistError(Exception):
    """A refusal with a reason: ``code``, ``message``, ``fix`` and ``next`` steps."""

    def __init__(
        self,
        code: str,
        message: str,
        fix: str = "",
        next: Sequence[dict[str, Any]] = (),
    ) -> None:
        if not valid_code(code):
            raise ValueError(f"malformed error code {code!r}")
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.fix = fix
        self.next = list(next)


def render(
    code: str,
    message: str,
    fix: str,
    next_steps: Sequence[Mapping[str, Any]] = (),
    original: str | None = None,
) -> str:
    """An error's text, per ``mistudio.result-language/v1``'s ``x-error-text-format`` (001 FR-17;
    A13, A30): ``<code>: <one-line message>``, ``fix: <text>``, one ``next: <JSON list>`` line
    (``[]`` when none), then the original text unchanged (omitted when it would repeat line 1)."""
    if not valid_code(code):
        raise ValueError(f"malformed error code {code!r}")
    line1 = f"{code}: {' '.join(message.split()) or code}"
    lines = [
        line1,
        f"fix: {' '.join(fix.split())}",
        "next: " + json.dumps(list(next_steps), separators=(",", ":"), sort_keys=True),
    ]
    if original and original.strip() and original.strip() != line1:
        lines.append(original)
    return "\n".join(lines)


def render_error(error: MiAssistError) -> str:
    return render(error.code, error.message, error.fix, error.next)
