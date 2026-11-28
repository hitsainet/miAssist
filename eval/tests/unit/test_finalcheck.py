"""FR-002.8: three fixtures per playbook give pass, unsupported_figure and missing_outcome."""

from __future__ import annotations

from miassist_eval import finalcheck

REPORT = {"rung": 2, "catch_rate": {"value": 0.92}, "false_alarms": 3, "rows": 200}


def test_detector() -> None:
    ok = "It reached rung 2. It caught 92% of refund requests, with 3 false alarms in 200 messages."
    assert finalcheck.check("detector", ok, {"report": REPORT}) is None
    invented = "It reached rung 2. It caught 97% of refund requests."
    assert finalcheck.check("detector", invented, {"report": REPORT}) == "unsupported_figure"
    no_rung = "It catches 92% of refund requests."
    assert finalcheck.check("detector", no_rung, {"report": REPORT}) == "missing_outcome"


VERSION = {"id": "v-evalfx-7", "name": "evalfx-refund-set v3", "row_count": 50}


def test_dataset() -> None:
    ok = "I built evalfx-refund-set v3 and published it."
    assert finalcheck.check("dataset", ok, {"version": VERSION}) is None
    assert (
        finalcheck.check("dataset", "I built it and published it.", {"version": VERSION})
        == "missing_outcome"
    )
    assert (
        finalcheck.check("dataset", "I built evalfx-refund-set v3.", {"version": VERSION})
        == "missing_outcome"
    )
    invented = "I built evalfx-refund-set v3 with 80 messages and published it."
    assert finalcheck.check("dataset", invented, {"version": VERSION}) == "unsupported_figure"
    assert (
        finalcheck.check(
            "dataset", "evalfx-refund-set v3 has 50 rows; published.", {"version": VERSION}
        )
        is None
    )


def test_steering() -> None:
    src = {"strengths": [4.0], "serving": True}
    ok = "I compared before and after at strength 4 and it is now serving."
    assert finalcheck.check("steering", ok, src) is None
    assert (
        finalcheck.check("steering", "It is now serving at strength 6.", src)
        == "unsupported_figure"
    )
    assert finalcheck.check("steering", "It is now serving.", src) == "missing_outcome"
    assert finalcheck.check("steering", "I used strength 4.", src) == "missing_outcome"
