"""The contract's names (001 FTASKS 1.5; A6 as amended, A30)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from miassist.errors import ERROR_CODE_PATTERN

SCHEMAS = Path(__file__).resolve().parents[2] / "docs" / "schemas"


def load(name: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((SCHEMAS / name).read_text())
    return data


def keys_named(node: Any, name: str) -> int:
    count = 0
    if isinstance(node, dict):
        props = node.get("properties")
        if isinstance(props, dict) and name in props:
            count += 1
        for key in ("required", "dependentRequired"):
            value = node.get(key)
            if isinstance(value, list) and name in value:
                count += 1
            if isinstance(value, dict) and name in value:
                count += 1
        count += sum(keys_named(v, name) for v in node.values())
    elif isinstance(node, list):
        count += sum(keys_named(v, name) for v in node)
    return count


def test_a6_def_names() -> None:
    defs = load("mistudio-result-language-v1.json")["$defs"]
    for name in ("approval", "next_step", "unavailable"):
        assert name in defs
    assert set(defs) == {
        "app_id",
        "approval_status",
        "approval",
        "call_again",
        "next_step",
        "tool_name",
        "unavailable",
        "error_body",
        "error_code",
        "explanation",
        "assist_result",
        "result_fields",
    }


def test_root_key_is_next_steps_and_no_key_is_next() -> None:
    doc = load("mistudio-result-language-v1.json")
    assert "next_steps" in doc["$defs"]["result_fields"]["properties"]
    assert doc["$ref"] == "#/$defs/result_fields"
    assert keys_named(doc, "next") == 0, "the result language never names a key `next` (A6)"


def test_error_code_pattern_is_a30s() -> None:
    error_code = load("mistudio-result-language-v1.json")["$defs"]["error_code"]
    assert error_code["pattern"] == ERROR_CODE_PATTERN == r"^[a-z][a-z0-9_]*(\.[a-z0-9_]+)?$"
    assert error_code["maxLength"] == 64


def test_error_text_line1_embeds_error_code() -> None:
    doc = load("mistudio-result-language-v1.json")
    line1 = doc["x-error-text-format"]["lines"][0]["pattern"]
    inner = doc["$defs"]["error_code"]["pattern"].removeprefix("^").removesuffix("$")
    assert line1 == f"^({inner}): ([^\\n]+)$"


def test_ids_and_contract_names() -> None:
    for file, contract in (
        ("mistudio-result-language-v1.json", "mistudio.result-language/v1"),
        ("mistudio-playbook-v1.json", "mistudio.playbook/v1"),
    ):
        doc = load(file)
        assert (
            doc["$id"]
            == f"https://raw.githubusercontent.com/hitsainet/miAssist/main/docs/schemas/{file}"
        )
        assert doc["x-contract"] == contract
        assert doc["$schema"] == "https://json-schema.org/draft/2020-12/schema"


def test_approval_statuses_are_seven() -> None:
    defs = load("mistudio-result-language-v1.json")["$defs"]
    assert defs["approval_status"]["enum"] == [
        "pending",
        "approved",
        "executing",
        "executed",
        "failed",
        "rejected",
        "expired",
    ]
    assert defs["app_id"]["enum"] == ["miworkbench", "miserver", "midataworks", "miforge"]
