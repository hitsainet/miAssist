"""JSON Schemas for every file kind this feature writes or reads (FR-002.4, 25, 27, 30, 43; FTDD §4).

Cassettes are NOT among them: a take's ``cassette.json`` validates against Core's
``tests/fixtures/miassist-cassette-v1.schema.json`` (A22, R1M-5), read through
``MIASSIST_CORE_CASSETTE_SCHEMA`` (FTID §9), never a copy.
"""

from __future__ import annotations

import json
import os
from functools import cache
from pathlib import Path
from typing import Any

import jsonschema

from miassist_eval import classes

EVAL_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = EVAL_ROOT.parent
SCHEMA_DIR = EVAL_ROOT / "schemas"
KINDS = (
    "eval-goals",
    "eval-fixtures",
    "bar",
    "eval-run",
    "eval-report",
    "eval-manual",
    "eval-take",
    "route-profile",
)


@cache
def schema(kind: str) -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads((SCHEMA_DIR / f"{kind}-v1.json").read_text())
    return loaded


def errors(kind: str, instance: Any) -> list[str]:
    validator = jsonschema.Draft202012Validator(schema(kind))
    return [
        f"{'/'.join(str(p) for p in e.absolute_path) or '<root>'}: {e.message[:200]}"
        for e in validator.iter_errors(instance)
    ]


def validate(kind: str, instance: Any) -> None:
    found = errors(kind, instance)
    if found:
        raise ValueError(f"{kind}: " + "; ".join(found[:5]))


def core_cassette_schema_path() -> Path:
    default = REPO_ROOT / "tests" / "fixtures" / "miassist-cassette-v1.schema.json"
    return Path(os.environ.get("MIASSIST_CORE_CASSETTE_SCHEMA", default))


def core_cassette_schema() -> dict[str, Any]:
    """Core's cassette schema, or ``cassette_schema_missing`` (FTID §3.15, R3M-4)."""
    path = core_cassette_schema_path()
    if not path.is_file():
        raise classes.Refusal(classes.CASSETTE_SCHEMA_MISSING, str(path))
    loaded: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return loaded


def cassette_errors(cassette: Any) -> list[str]:
    validator = jsonschema.Draft202012Validator(core_cassette_schema())
    return [
        f"{'/'.join(str(p) for p in e.absolute_path) or '<root>'}: {e.message[:200]}"
        for e in validator.iter_errors(cassette)
    ]
