"""FR-002.43, FR-002.45: the manual result file; an item with no value reads not_run."""

from __future__ import annotations

from miassist_eval import report, schemas


def doc(items):
    return {
        "schema": "miassist.eval-manual/v1",
        "release": "0.1.0",
        "client": "desktop",
        "items": items,
    }


def test_a_valid_file() -> None:
    assert (
        schemas.errors(
            "eval-manual", doc([{"id": "m1", "result": "pass", "reason": None, "waiver": None}])
        )
        == []
    )


def test_an_unknown_result_fails() -> None:
    assert schemas.errors(
        "eval-manual", doc([{"id": "m1", "result": "ok", "reason": None, "waiver": None}])
    )


def test_an_item_with_no_value_counts_as_not_run() -> None:
    summary = report.manual_summary({"desktop": {"items": [{"id": "m1"}]}})
    assert summary["desktop"]["not_run"] == 1 and summary["desktop"]["pass"] == 0
