"""``x-annotation-rules`` as published (001 FPRD §5.1.5; A13, A30, R3M-8)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

SCHEMA = Path(__file__).resolve().parents[2] / "docs/schemas/mistudio-result-language-v1.json"


def rules() -> list[dict[str, Any]]:
    loaded: list[dict[str, Any]] = json.loads(SCHEMA.read_text())["x-annotation-rules"]
    return loaded


def test_seven_rules_with_levels() -> None:
    assert [r["id"] for r in rules()] == [f"AR-{n}" for n in range(1, 8)]
    assert all(r["level"] in ("must", "should") for r in rules())
    assert {r["id"]: r["level"] for r in rules()}["AR-6"] == "should"


def test_ar7_names_the_call_set_condition() -> None:
    """AR-7 is the round-2 wording: a relay carries its source's hints ONLY when its REST call set
    equals the source tool's; otherwise AR-3 and AR-4 apply. The v0.2 wording ("a proxied tool
    carries exactly its source app's hints") is wrong and must not come back."""
    ar7 = next(r for r in rules() if r["id"] == "AR-7")["rule"]
    assert "REST call set equals" in ar7
    assert "AR-3 and AR-4 apply" in ar7
    assert "proxied tool carries exactly" not in ar7


def test_read_only_and_destructive_definitions() -> None:
    by_id = {r["id"]: r["rule"] for r in rules()}
    assert "starts no job" in by_id["AR-3"] and "files no" in by_id["AR-3"]
    assert "HTTP method does not decide" in by_id["AR-3"]
    assert "deletes, purges, clears or cancels" in by_id["AR-4"]
    assert "idempotentHint and openWorldHint stay unset" in by_id["AR-5"]
