"""Every recorded Core result validates against the PUBLISHED file on disk (001 FR-12, AC-12.x;
FTASKS 9.3): ``structuredContent`` against ``$defs.assist_result`` of
``docs/schemas/mistudio-result-language-v1.json``, its text block equal to it, and every error's
first line against the file's ``x-error-text-format``. The scenarios are ``tests/support/
scenarios.py``'s, run through the real ASGI app at ``/mcp`` and at ``/p/<key>/mcp``."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from tests.support.scenarios import CORE_TOOLS, Scenario, run, scenarios

SCHEMAS = Path(__file__).resolve().parents[2] / "docs" / "schemas"
KEY = "abcdefghijklmnopqrstuvwxyz"


def _load(name: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((SCHEMAS / name).read_text())
    return data


def validator() -> Draft202012Validator:
    resources = [
        (doc["$id"], Resource.from_contents(doc))
        for doc in (_load("mistudio-result-language-v1.json"), _load("mistudio-playbook-v1.json"))
    ]
    root = _load("mistudio-result-language-v1.json")
    return Draft202012Validator(
        {"$ref": root["$id"] + "#/$defs/assist_result"},
        registry=Registry().with_resources(resources),
    )


VALIDATOR = validator()
ERROR_LINES = [
    re.compile(line["pattern"])
    for line in _load("mistudio-result-language-v1.json")["x-error-text-format"]["lines"]
]


def check(result: dict[str, Any], scenario: Scenario) -> None:
    if scenario.error:
        assert result["isError"] is True, scenario.id
        lines = result["content"][0]["text"].splitlines()
        for pattern, line in zip(ERROR_LINES, lines, strict=False):
            assert pattern.match(line), (scenario.id, line)
        return
    assert result["isError"] is False, (scenario.id, result["content"])
    structured = result["structuredContent"]
    errors = sorted(VALIDATOR.iter_errors(structured), key=lambda e: list(e.path))
    assert not errors, (scenario.id, [f"{list(e.path)}: {e.message}" for e in errors])
    assert json.loads(result["content"][0]["text"]) == structured, scenario.id


@pytest.mark.parametrize("scenario", scenarios(), ids=lambda s: s.id)
@pytest.mark.parametrize("key", [None, KEY], ids=["bare", "keyed"])
def test_every_recorded_result(scenario: Scenario, key: str | None) -> None:
    check(run(scenario, key=key).result, scenario)


@pytest.mark.parametrize("scenario", scenarios(), ids=lambda s: s.id)
def test_every_recorded_result_expert(scenario: Scenario) -> None:
    result = run(scenario, key=KEY, level="expert").result
    check(result, scenario)
    # the level is the one in force AFTER the call: setting beginner or forgetting brings it back
    if not scenario.error and scenario.id not in ("set-guidance-beginner", "reset"):
        assert "explain" not in result["structuredContent"], scenario.id


def test_every_core_tool_is_recorded() -> None:
    assert {s.tool for s in scenarios()} >= set(CORE_TOOLS)


def test_the_validator_bites() -> None:
    """A result carrying ``next_steps[0].arguments`` (the pre-A6 name) is invalid."""
    bad = {
        "guidance": "expert",
        "data": {},
        "next_steps": [{"tool": "miassist_status", "arguments": {}, "why": "x"}],
    }
    assert list(VALIDATOR.iter_errors(bad))
