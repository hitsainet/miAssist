"""Every cassette validates: the format (``Cassette``) and each answer body against its route's
answer schema in the committed OpenAPI snapshot (001 FR-31; FTASKS 4.5). Recordings are
operator-run (M14), so the tree may hold none yet; the validator is proven on a built cassette."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator

from tests.support.cassette import FORMAT, ROOT, Cassette, load

SNAPSHOTS = Path(__file__).resolve().parents[1] / "fixtures/openapi"


def answer_errors(cassette: Cassette) -> list[str]:
    errors = []
    for rec in cassette.records:
        snapshot = json.loads((SNAPSHOTS / f"{rec.app}.json").read_text())["paths"]
        operation = snapshot.get(rec.request.route, {}).get(rec.request.method.lower())
        if operation is None:
            errors.append(
                f"records[{rec.seq}]: {rec.request.method} {rec.request.route} is not pinned"
            )
            continue
        response = operation.get("responses", {}).get(str(rec.answer.status))
        schema = (response or {}).get("content", {}).get("application/json", {}).get("schema")
        if schema is None:
            continue
        for error in Draft202012Validator(schema).iter_errors(rec.answer.body):
            errors.append(f"records[{rec.seq}].answer.body: {error.message}")
    return errors


CASSETTES = sorted(ROOT.rglob("*.cassette.json")) if ROOT.is_dir() else []


@pytest.mark.parametrize("path", CASSETTES, ids=[str(p.relative_to(ROOT)) for p in CASSETTES])
def test_cassette_valid(path: Path) -> None:
    assert answer_errors(load(path)) == []


def built(body: Any, route: str = "/api/v1/approvals/{approval_id}") -> Cassette:
    return Cassette.model_validate(
        {
            "format": FORMAT,
            "name": "built",
            "source": "hand_written",
            "records": [
                {
                    "seq": 0,
                    "app": "miforge",
                    "app_version": "0.5.0",
                    "time": "2026-11-16T05:00:00-05:00",
                    "request": {"method": "GET", "path": "/x", "route": route},
                    "answer": {"status": 200, "body": body},
                }
            ],
        }
    )


def test_the_validator_bites() -> None:
    assert answer_errors(built({}, route="/api/v1/not-pinned"))
    assert answer_errors(built("not an object", route="/api/health"))
