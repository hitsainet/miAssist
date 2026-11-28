"""Result-language shapes (FR-002.16; FTASKS 10.2; CHAIN_PLAN A6 as amended, A30). Checked on the
miAssist surface only; the baseline's servers carry today's legacy ``next`` and approval fields and
are measured as they are (C-10)."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from functools import cache
from pathlib import Path
from typing import Any

import jsonschema

REPO_ROOT = Path(__file__).resolve().parents[2]
CONTRACT = REPO_ROOT / "docs" / "schemas" / "mistudio-result-language-v1.json"
ERROR_LINE_1 = re.compile(r"^([a-z][a-z0-9_]*(\.[a-z0-9_]+)?): ([^\n]+)$")


@cache
def contract() -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads(CONTRACT.read_text(encoding="utf-8"))
    return loaded


def check_miassist(structured: Any, is_error: bool, text: str) -> list[str]:
    """Problems with one miAssist tool result: the structured content against the contract, and an
    error's line 1 (A30)."""
    out = []
    if isinstance(structured, Mapping):
        validator = jsonschema.Draft202012Validator(contract())
        out += [f"structured: {e.message[:160]}" for e in validator.iter_errors(dict(structured))]
    if is_error and not ERROR_LINE_1.match(text.splitlines()[0] if text else ""):
        out.append(f"error line 1 does not start with a lower-case error_code: {text[:80]!r}")
    return out


def check_baseline(structured: Any, is_error: bool, text: str) -> list[str]:
    """Today's servers: no new shape is required of them."""
    return []


def check(surface: str, structured: Any, is_error: bool, text: str) -> list[str]:
    if surface == "miassist":
        return check_miassist(structured, is_error, text)
    return check_baseline(structured, is_error, text)
