"""Error text follows the schema's ``x-error-text-format`` (001 FR-17; FTASKS 5.4)."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from miassist.errors import MiAssistError, render, render_error

DOC = json.loads(
    (
        Path(__file__).resolve().parents[2] / "docs/schemas/mistudio-result-language-v1.json"
    ).read_text()
)
LINES = [re.compile(line["pattern"]) for line in DOC["x-error-text-format"]["lines"]]
ERROR_CODE = re.compile(DOC["$defs"]["error_code"]["pattern"])

CASES = {
    "own-error": ("floor_limit", "too many", "wait an hour", [], None),
    "app-error": (
        "midataworks.unprocessable",
        "bad body",
        "fix the field",
        [],
        "UNPROCESSABLE: bad body\n{...}",
    ),
    "with-next": (
        "unknown_term",
        "no such term",
        "see the glossary",
        [{"tool": "miassist_glossary", "args": {}, "why": "List the terms."}],
        None,
    ),
}


@pytest.mark.parametrize("case", sorted(CASES))
def test_grammar(case: str) -> None:
    code, message, fix, steps, original = CASES[case]
    text = render(code, message, fix, steps, original)
    lines = text.split("\n")
    for pattern, line in zip(LINES, lines[:3], strict=True):
        assert pattern.fullmatch(line), (pattern.pattern, line)
    assert ERROR_CODE.fullmatch(LINES[0].fullmatch(lines[0]).group(1))  # type: ignore[union-attr]
    assert json.loads(LINES[2].fullmatch(lines[2]).group(1)) == steps  # type: ignore[union-attr]
    if original:
        assert "\n".join(lines[3:]) == original
    else:
        assert len(lines) == 3


def test_from_error() -> None:
    text = render_error(MiAssistError("needs_your_reason", "say why", fix="give a reason"))
    assert text.splitlines()[:2] == ["needs_your_reason: say why", "fix: give a reason"]


def test_multiline_message_stays_one_line() -> None:
    assert render("floor_limit", "a\nb", "c\nd").splitlines()[:2] == [
        "floor_limit: a b",
        "fix: c d",
    ]
