"""No tool takes a secret (001 FR-27, AC-27.3; A14, A17): no input-schema property of any tool in
the live registry, all four apps installed and every chain's specs loaded, names a token, password,
secret, API key, credential or authorization. Agents never pass the operator's credentials."""

from __future__ import annotations

import re
from typing import Any

from mcp import Client

from tests.support.fake_apps import all_fakes
from tests.support.servers import make_server

ALL = ("miworkbench", "miserver", "midataworks", "miforge")
SECRET_LIKE = re.compile(r"token|passw|secret|api_?key|credential|authori[sz]ation|cookie", re.I)


def property_names(schema: Any) -> list[str]:
    out: list[str] = []
    if isinstance(schema, dict):
        for name, sub in (schema.get("properties") or {}).items():
            out.append(name)
            out += property_names(sub)
        for key in ("items", "anyOf", "oneOf", "allOf", "$defs"):
            value = schema.get(key)
            if isinstance(value, list):
                for item in value:
                    out += property_names(item)
            elif isinstance(value, dict):
                for item in value.values() if key == "$defs" else [value]:
                    out += property_names(item)
    return out


async def test_no_secret_parameters() -> None:
    mcp, _ = make_server(ALL, all_fakes())
    async with Client(mcp) as client:
        tools = (await client.list_tools()).tools
    assert tools
    found = [
        (t.name, name)
        for t in tools
        for name in property_names(t.input_schema)
        if SECRET_LIKE.search(name)
    ]
    assert found == []


def test_scanner_self_test() -> None:
    schema = {
        "properties": {
            "term": {"type": "string"},
            "options": {"anyOf": [{"properties": {"hf_token": {"type": "string"}}}]},
        }
    }
    assert [n for n in property_names(schema) if SECRET_LIKE.search(n)] == ["hf_token"]
