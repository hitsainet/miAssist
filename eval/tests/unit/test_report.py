"""FR-002.30-FR-002.34, FR-002.37a, FR-002.39, FR-002.44-FR-002.46."""

from __future__ import annotations

import copy

import pytest
import yaml

from miassist_eval import report
from tests.support.records import PLAYBOOK_OF, SHA, rec

BAR = yaml.safe_load(open(report.__file__.replace("miassist_eval/report.py", "bar.yaml")))


def confirmed_bar() -> dict:
    bar = copy.deepcopy(BAR)
    bar.update(
        status="confirmed",
        confirmed_on="2026-11-20",
        words="ok",
        baseline_report="b",
        baseline_goal_set_sha256=SHA,
    )
    return bar


def all_cells(n: int = 10, **kw) -> list[dict]:
    out = []
    for goal in PLAYBOOK_OF:
        for client in ("claude_code", "open_webui"):
            out += [rec(i + 100 * len(out), goal=goal, client=client, **kw) for i in range(n)]
    return out


def baseline(n: int = 10, bar_calls: int = 40) -> list[dict]:
    out = []
    for goal in PLAYBOOK_OF:
        for client in ("claude_code", "open_webui"):
            out += [
                rec(
                    1000 + i + 100 * len(out),
                    goal=goal,
                    client=client,
                    surface="baseline",
                    bar_calls=bar_calls,
                )
                for i in range(n)
            ]
    return out


def summarise(records, **kw):
    return report.summarise(
        "t",
        records,
        kw.pop("rejected", []),
        kw.pop("bar", confirmed_bar()),
        kw.pop("approved", True),
        PLAYBOOK_OF,
        ["s"],
        **kw,
    )


def cell(summary, playbook, client="claude_code", surface="miassist", tier="1b"):
    return next(c for c in summary["cells"] if c["key"] == [playbook, client, surface, tier])


def test_nine_valid_runs_read_not_measured_even_if_all_succeeded() -> None:
    s = summarise([rec(i) for i in range(9)])
    assert cell(s, "detector-probe")["verdicts"]["success"] == "NOT MEASURED"


def test_no_attempt_is_not_run() -> None:
    s = summarise([rec(i) for i in range(10)])
    assert cell(s, "dataset")["verdicts"] == {
        "success": "NOT RUN",
        "calls": "NOT RUN",
        "time": "NOT RUN",
    }


def test_first_ten_in_attempt_order() -> None:
    runs = [rec(i, "failed", "time_limit") for i in range(2)] + [rec(i + 2) for i in range(10)]
    assert sum(r["outcome"] == "success" for r in report.first10(runs)) == 8
    assert report.verdicts(runs, confirmed_bar(), 40)["success"] == "FAIL"


def test_invalid_runs_are_skipped_not_counted() -> None:
    runs = [rec(0, "invalid", "provider_error")] + [rec(i + 1) for i in range(10)]
    assert report.verdicts(runs, confirmed_bar(), 40)["success"] == "PASS"


def test_bar_met_only_when_every_required_cell_passes() -> None:
    s = summarise(all_cells(), baseline=baseline())
    assert s["verdict"] == "BAR MET", s["reasons"]


def test_removing_one_required_cell_reads_bar_not_met_naming_it_not_run() -> None:
    runs = [
        r
        for r in all_cells()
        if not (r["goal"]["id"] == "tone-warmer" and r["client"]["name"] == "open_webui")
    ]
    s = summarise(runs, baseline=baseline())
    assert s["verdict"] == "BAR NOT MET"
    assert "steering/open_webui/miassist/1b" in s["reasons"][0] and "NOT RUN" in s["reasons"][0]


def test_the_provisional_bar_heading() -> None:
    s = summarise(all_cells(), bar=BAR, baseline=baseline())
    assert "PROVISIONAL BAR" in s["headings"]


def test_goals_not_approved_heading_and_no_verdict() -> None:
    s = summarise(all_cells(), approved=False, baseline=baseline())
    assert "GOALS NOT APPROVED" in s["headings"] and s["verdict"] == "NO VERDICT"
    assert all(set(c["verdicts"].values()) == {"NO VERDICT"} for c in s["cells"])


def test_comparability_refused_by_model_id() -> None:
    s = summarise(all_cells(model="m-2"), baseline=baseline())
    why = {c["why"] for c in s["comparisons"]}
    assert why == {"not_comparable: model id"}
    assert cell(s, "detector-probe")["verdicts"]["calls"] == "NOT MEASURED"


def test_comparability_refused_by_goal_set_hash() -> None:
    s = summarise(all_cells(goal_sha="b" * 64), baseline=baseline())
    assert {c["why"] for c in s["comparisons"]} == {"not_comparable: goal set"}


def test_reference_path_fallback_is_flagged() -> None:
    base = baseline(bar_calls=40)
    for r in base:
        r["outcome"] = "failed"
    s = summarise(all_cells(), baseline=base, reference_calls={"detector-probe": 30})
    c = cell(s, "detector-probe")
    assert c["baseline_basis"] == "reference_path"
    assert c["verdicts"]["calls"] == "PASS"  # 10 <= 0.5 * 30


def test_manual_not_run_counted_and_blocking() -> None:
    manual = {
        "desktop": {"items": [{"id": "m1", "result": "pass"}, {"id": "m2", "result": "not_run"}]}
    }
    s = summarise(all_cells(), baseline=baseline(), manual=manual)
    assert s["manual"]["desktop"]["not_run"] == 1 and s["verdict"] == "BAR NOT MET"


def test_a_manual_fail_blocks_without_a_waiver_and_not_with_one() -> None:
    fail = {"desktop": {"items": [{"id": "m1", "result": "fail"}]}}
    assert summarise(all_cells(), baseline=baseline(), manual=fail)["verdict"] == "BAR NOT MET"
    waived = {
        "desktop": {
            "items": [
                {
                    "id": "m1",
                    "result": "fail",
                    "waiver": {"by": "operator", "on": "d", "words": "known"},
                }
            ]
        }
    }
    assert summarise(all_cells(), baseline=baseline(), manual=waived)["verdict"] == "BAR MET"


def test_a_failed_tier2_run_blocks() -> None:
    assert summarise(all_cells(), baseline=baseline(), tier2_ok=False)["verdict"] == "BAR NOT MET"


# ---------------------------------------------------------------- the baseline (FR-002.37a)
def base_cell(off: int, n: int = 10) -> list[dict]:
    return [
        rec(
            i,
            "failed" if i < off else "success",
            "off_recording" if i < off else None,
            surface="baseline",
        )
        for i in range(n)
    ]


def test_baseline_coverage_and_both_success_figures() -> None:
    c = report.coverage(base_cell(3))
    assert c == {
        "coverage": 0.7,
        "success_off_recording_as_failure": "7/10",
        "success_on_recording_only": "7/7",
        "off_recording": 3,
        "flag": None,
    }


def test_low_coverage_under_70_percent() -> None:
    assert report.coverage(base_cell(4))["flag"] == "LOW COVERAGE"


def test_baseline_cells_carry_coverage_and_the_live_row() -> None:
    live = [rec(500, surface="baseline", bar_calls=60), rec(501, surface="baseline", bar_calls=60)]
    s = summarise(base_cell(3), live=live)
    c = cell(s, "detector-probe", surface="baseline")
    assert c["coverage"]["off_recording"] == 3
    assert c["live"]["median_bar_calls"] == 60
    assert c["live"]["flag"] and "25%" in c["live"]["flag"]


def test_tier_agreement_flags_both_disagreements() -> None:
    low = base_cell(6)  # 4/10
    high = base_cell(0)  # 10/10
    assert report.tier_agreement(rec(1, "success", surface="baseline"), low)
    assert report.tier_agreement(rec(1, "failed", "x", surface="baseline"), high)
    assert report.tier_agreement(rec(1, "success", surface="baseline"), high) is None


def test_render_reads_the_summary_only(tmp_path) -> None:
    s = summarise(all_cells(), baseline=baseline())
    report.write(tmp_path, s)
    text = (tmp_path / "REPORT.md").read_text()
    assert "BAR MET" in text and "## Method" in text and ("EST" in text or "EDT" in text)


@pytest.mark.parametrize("k,n", [(9, 10), (10, 10), (0, 10)])
def test_wilson_is_informational(k: int, n: int) -> None:
    lo, hi = report.wilson(k, n)
    assert 0 <= lo <= k / n <= hi <= 1


def test_a_baseline_cell_with_live_recordings_but_no_live_row_fails_validation() -> None:
    from miassist_eval import schemas

    live = [rec(500, surface="baseline", bar_calls=10)]
    s = summarise(base_cell(0), live=live)
    assert schemas.errors("eval-report", s) == []
    cell(s, "detector-probe", surface="baseline").pop("live")
    assert schemas.errors("eval-report", s)


def test_a_baseline_cell_without_coverage_fails_validation() -> None:
    from miassist_eval import schemas

    s = summarise(base_cell(3))
    cell(s, "detector-probe", surface="baseline").pop("coverage")
    assert schemas.errors("eval-report", s)
