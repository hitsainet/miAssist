"""The approval status mapping vectors (001 AC-12.4, FTASKS 5.1)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator

from miassist.errors import MiAssistError
from miassist.results.approvals import approval_object, map_status

ROOT = Path(__file__).resolve().parents[2]
VECTORS = json.loads((ROOT / "tests/fixtures/approval_status_vectors.json").read_text())
SCHEMA = json.loads((ROOT / "docs/schemas/mistudio-result-language-v1.json").read_text())


def approval_validator() -> Draft202012Validator:
    return Draft202012Validator({**SCHEMA, "$ref": "#/$defs/approval"})


@pytest.mark.parametrize(
    "row",
    VECTORS["rows"],
    ids=[f"{r['app']}-{r['style']}-{r['app_status']}" for r in VECTORS["rows"]],
)
def test_approval_status(row: dict[str, str]) -> None:
    style: Any = "server_executed" if row["style"] == "relay" else row["style"]
    assert map_status(row["app"], row["app_status"], style) == (row["status"], row["then"])
    body = {"id": "a1", "status": row["app_status"], "action": "x"}
    call_again = (
        {"tool": "miassist_x", "args": {"approval_id": "a1"}}
        if row["then"] == "call_again_with"
        else None
    )
    approval = approval_object(
        row["app"], body, style=style, summary="what happens", call_again_with=call_again
    )
    approval_validator().validate(approval)
    assert approval["status"] == row["status"] and approval["decide_in"] == row["app"]
    if row["then"] == "call_again_with":
        assert approval["call_again_with"] == call_again


@pytest.mark.parametrize("row", VECTORS["unknown"], ids=lambda r: f"{r['app']}-{r['app_status']}")
def test_unknown_status_refused(row: dict[str, str]) -> None:
    style: Any = row["style"]
    with pytest.raises(MiAssistError):
        map_status(row["app"], row["app_status"], style)


def test_server_executed_never_approved() -> None:
    for row in VECTORS["rows"]:
        if row["then"] == "server_runs":
            assert row["status"] != "approved"
