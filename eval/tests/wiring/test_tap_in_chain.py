"""FR-002.17 wiring: a run whose tap misses calls is invalid (count_mismatch)."""

from __future__ import annotations

import functools
from pathlib import Path

from miassist_eval import suite, tap
from tests.support import suites


async def test_a_tap_that_skips_tools_call_makes_the_run_invalid(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(
        suite, "Tap", functools.partial(tap.Tap, skip_methods=frozenset({"tools/call"}))
    )
    result = await suites.suite(tmp_path).run()
    assert result.records[0]["outcome"] == "invalid"
    assert result.records[0]["cls"] == "count_mismatch"
    assert len(result.records) == 3, "an invalid run is re-attempted up to twice"


async def test_with_the_tap_the_counts_agree(tmp_path: Path) -> None:
    result = await suites.suite(tmp_path).run()
    assert result.records[0]["outcome"] == "success"
