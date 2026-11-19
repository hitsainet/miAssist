"""The playbook file's two relative ``$ref``s resolve into the result-language file (AC-13.2)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError
from referencing import Registry, Resource

SCHEMAS = Path(__file__).resolve().parents[2] / "docs" / "schemas"


def load(name: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((SCHEMAS / name).read_text())
    return data


def registry() -> Registry:
    resources = []
    for name in ("mistudio-result-language-v1.json", "mistudio-playbook-v1.json"):
        doc = load(name)
        resources.append((doc["$id"], Resource.from_contents(doc)))
    return Registry().with_resources(resources)


def status_validator() -> Draft202012Validator:
    playbook = load("mistudio-playbook-v1.json")
    schema = {"$ref": playbook["$id"] + "#/$defs/playbook_status"}
    return Draft202012Validator(schema, registry=registry())


STATUS = {
    "playbook_id": "start-miforge",
    "playbook_version": 1,
    "finished": False,
    "where": "look-around",
    "done": [],
    "next": {"tool": "miassist_overview", "args": {"app": "miforge"}, "why": "See what is there."},
    "waiting": [
        {
            "kind": "approval",
            "detail": "The operator decides it in miForge.",
            "approval": {
                "id": "a1",
                "status": "pending",
                "decide_in": "miforge",
                "then": "server_runs",
                "summary": "Start the run.",
            },
        }
    ],
    "expected": "A first look at miForge.",
    "not_in_this_installation": [],
}


def test_cross_file_refs_resolve() -> None:
    status_validator().validate(STATUS)


def test_the_refs_bite() -> None:
    bad_next = {**STATUS, "next": {"tool": "miassist_overview", "args": {}, "reason": "x"}}
    with pytest.raises(ValidationError):
        status_validator().validate(bad_next)
    bad_approval = json.loads(json.dumps(STATUS))
    bad_approval["waiting"][0]["approval"]["status"] = "consumed"
    with pytest.raises(ValidationError):
        status_validator().validate(bad_approval)


def test_every_external_ref_names_a_def() -> None:
    result_defs = set(load("mistudio-result-language-v1.json")["$defs"])
    refs: list[str] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            ref = node.get("$ref")
            if isinstance(ref, str) and not ref.startswith("#"):
                refs.append(ref)
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(load("mistudio-playbook-v1.json"))
    assert sorted(refs) == [
        "mistudio-result-language-v1.json#/$defs/approval",
        "mistudio-result-language-v1.json#/$defs/next_step",
    ]
    for ref in refs:
        assert ref.split("#/$defs/")[1] in result_defs
