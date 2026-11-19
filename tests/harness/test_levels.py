"""FR-7's side-effect test (001 AC-7.1; FTASKS 10.5; R1 review fix OR1-001-6, 2026-11-16): for
every Core tool and every recorded scenario, running at beginner and at expert makes the same app
requests (method, path, query, body, count), the same store writes, and returns the same ``data``
and ``next_steps``; only ``explain`` differs."""

from __future__ import annotations

from typing import Any

import pytest

from tests.support.memory_store import MemoryStore
from tests.support.scenarios import Scenario, run, scenarios

KEY = "lkjhgfdsapoiuytrewqmnbvcxz"
#: These scenarios change the level themselves, so the level after the call is theirs.
SETS_LEVEL = {"set-guidance-expert", "set-guidance-beginner", "reset"}


def level_free(data: Any) -> Any:
    """``data`` without the fields that REPORT the level by design: ``level`` (FR-8 "the level in
    use", FR-23) and a playbook's ``guide`` entry, rendered at the reader's level (FTID §3.8's
    ``guide_entry(pb, level)``; OVN-miassist-core-28). Everything else must be identical."""
    if not isinstance(data, dict):
        return data
    out = {k: v for k, v in data.items() if k != "level"}
    for key in ("playbooks", "playbook"):
        value = out.get(key)
        if isinstance(value, list):
            out[key] = [{k: v for k, v in e.items() if k != "guide"} for e in value]
        elif isinstance(value, dict):
            out[key] = {k: v for k, v in value.items() if k != "guide"}
    return out


@pytest.mark.parametrize("scenario", scenarios(), ids=lambda s: s.id)
def test_identical_side_effects(scenario: Scenario) -> None:
    seen = {}
    for level in ("beginner", "expert"):
        store = MemoryStore()
        done = run(scenario, key=KEY, store=store, level=level)
        result = done.result
        structured = result.get("structuredContent") or {}
        seen[level] = (
            done.app_requests(),
            store.write_calls,
            result["isError"],
            level_free(structured.get("data")),
            structured.get("next_steps"),
            structured.get("guidance") if scenario.id in SETS_LEVEL else None,
        )
        if level == "expert" and not result["isError"] and scenario.id not in SETS_LEVEL:
            assert "explain" not in structured, scenario.id
    assert seen["beginner"][:5] == seen["expert"][:5], scenario.id


def test_the_comparison_sees_app_requests() -> None:
    """Not vacuous: an overview scenario makes app requests at both levels."""
    scenario = next(s for s in scenarios() if s.id == "overview-miforge")
    done = run(scenario, key=KEY, level="expert")
    assert done.app_requests()
