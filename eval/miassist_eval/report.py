"""Cells, verdicts, comparability, the bar, the baseline's coverage and live row, tier agreement and
the release verdict (FR-002.30-FR-002.34, FR-002.37, FR-002.37a, FR-002.39, FR-002.44-FR-002.46;
FTID §3.8, §7.2; TD-8, TD-9). ``summary.json`` first; ``REPORT.md`` is rendered from it only."""

from __future__ import annotations

import json
import math
import statistics
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from miassist_eval import classes, schemas
from miassist_eval.clock import to_et

PASS, FAIL, NOT_MEASURED, NOT_RUN = "PASS", "FAIL", "NOT MEASURED", "NOT RUN"
BAR_MET, BAR_NOT_MET, NO_VERDICT = "BAR MET", "BAR NOT MET", "NO VERDICT"
PROVISIONAL = "PROVISIONAL BAR"
LOW_COVERAGE = "LOW COVERAGE"
CellKey = tuple[str, str, str, str]  # playbook, client, surface, tier


def cell_key(r: Mapping[str, Any], playbook_of: Mapping[str, str]) -> CellKey:
    return (
        playbook_of.get(r["goal"]["id"], r["goal"]["id"]),
        r["client"]["name"],
        r["surface"],
        r["tier"],
    )


def first10(records: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    """The first ten valid runs in attempt order (FR-002.32)."""
    ordered = sorted(records, key=lambda r: (r.get("attempt_order", 0), r["run_id"]))
    return [r for r in ordered if r["outcome"] != classes.INVALID][:10]


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float] | None:
    """Informational only (TD-9); the verdict uses M10's count."""
    if n == 0:
        return None
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (round(centre - half, 4), round(centre + half, 4))


def median(values: Sequence[float]) -> float | None:
    return statistics.median(values) if values else None


def verdicts(
    records: Sequence[Mapping[str, Any]], bar: Mapping[str, Any], baseline_median: float | None
) -> dict[str, str]:
    """PASS, FAIL, NOT MEASURED or NOT RUN per criterion (FTID §7.2)."""
    if not records:
        return {"success": NOT_RUN, "calls": NOT_RUN, "time": NOT_RUN}
    ten = first10(records)
    if len(ten) < 10:
        return {"success": NOT_MEASURED, "calls": NOT_MEASURED, "time": NOT_MEASURED}
    crit = bar["criteria"]
    ok = sum(r["outcome"] == classes.SUCCESS for r in ten)
    fast = sum(
        r["time"].get("first_useful_active_s") is not None
        and r["time"]["first_useful_active_s"] < crit["first_useful_active"]["seconds"]
        for r in ten
    )
    succeeded = [r["calls"]["bar_calls"] for r in ten if r["outcome"] == classes.SUCCESS]
    mine = median(succeeded)
    if baseline_median is None or mine is None:
        calls = NOT_MEASURED
    else:
        calls = PASS if mine <= (1 - crit["calls_reduction"]["min"]) * baseline_median else FAIL
    return {
        "success": PASS if ok >= crit["success"]["k"] else FAIL,
        "calls": calls,
        "time": PASS if fast >= crit["first_useful_active"]["k"] else FAIL,
    }


def baseline_median(
    records: Sequence[Mapping[str, Any]], reference_calls: int | None
) -> tuple[float | None, str]:
    succeeded = [
        r["calls"]["bar_calls"] for r in first10(records) if r["outcome"] == classes.SUCCESS
    ]
    if len(succeeded) >= 3:
        return median(succeeded), "baseline_runs"
    return (float(reference_calls) if reference_calls is not None else None), "reference_path"


def comparable(a: Mapping[str, Any], b: Mapping[str, Any]) -> str | None:
    """FR-002.31: one tier, one client, one model id served, one goal-set hash."""
    fields: tuple[tuple[str, tuple[str, ...]], ...] = (
        ("tier", ("tier",)),
        ("client", ("client", "name")),
        ("model id", ("model", "served")),
        ("goal set", ("goal", "goal_set_sha256")),
    )
    for name, path in fields:
        if _dig(a, path) != _dig(b, path):
            return f"{classes.NOT_COMPARABLE}: {name}"
    return None


def _dig(record: Mapping[str, Any], path: tuple[str, ...]) -> Any:
    node: Any = record
    for part in path:
        node = node[part]
    return node


def coverage(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """FR-002.37a: the baseline cell's coverage and its two success figures."""
    valid = [r for r in records if r["outcome"] != classes.INVALID]
    off = [r for r in valid if r.get("cls") == classes.OFF_RECORDING]
    on = [r for r in valid if r.get("cls") != classes.OFF_RECORDING]
    ok = sum(r["outcome"] == classes.SUCCESS for r in valid)
    share = (len(on) / len(valid)) if valid else None
    return {
        "coverage": share,
        "success_off_recording_as_failure": f"{ok}/{len(valid)}",
        "success_on_recording_only": f"{sum(r['outcome'] == classes.SUCCESS for r in on)}/{len(on)}",
        "off_recording": len(off),
        "flag": LOW_COVERAGE if share is not None and share < 0.70 else None,
    }


def live_row(live: Sequence[Mapping[str, Any]], replay_median: float | None) -> dict[str, Any]:
    calls = [r["calls"]["bar_calls"] for r in live]
    med = median(calls)
    flag = None
    if med is not None and replay_median:
        if abs(med - replay_median) / replay_median > 0.25:
            flag = "live bar-calls differ from the replays by more than 25%"
    return {
        "runs": [
            {
                "run_id": r["run_id"],
                "outcome": r["outcome"],
                "bar_calls": r["calls"]["bar_calls"],
                "active_s": r["time"].get("active_s"),
            }
            for r in live
        ],
        "median_bar_calls": med,
        "flag": flag,
    }


def tier_agreement(
    live: Mapping[str, Any], cell_records: Sequence[Mapping[str, Any]]
) -> str | None:
    """FR-002.39 (baseline): a live success in a cell under 5/10, or a live failure at 9/10 or
    more, is a disagreement."""
    ten = first10(cell_records)
    ok = sum(r["outcome"] == classes.SUCCESS for r in ten)
    if live["outcome"] == classes.SUCCESS and ok < 5:
        return f"live success in a cell at {ok}/{len(ten)}"
    if live["outcome"] != classes.SUCCESS and ok >= 9:
        return f"live failure in a cell at {ok}/{len(ten)}"
    return None


def manual_summary(manual: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for client, doc in manual.items():
        items = doc.get("items", [])
        out[client] = {
            "pass": sum(i.get("result") == "pass" for i in items),
            "fail": sum(i.get("result") == "fail" for i in items),
            "not_run": sum(i.get("result", "not_run") == "not_run" for i in items),
            "blocking": [
                i["id"] for i in items if i.get("result") == "fail" and not i.get("waiver")
            ],
            "unwaived_not_run": [
                i["id"]
                for i in items
                if i.get("result", "not_run") == "not_run" and not i.get("waiver")
            ],
        }
    return out


def release_verdict(
    cells: Sequence[Mapping[str, Any]], tier2_ok: bool, manual: Mapping[str, Any]
) -> tuple[str, list[str]]:
    """FR-002.34: BAR MET only when every required cell passes every criterion, every required
    tier-2 run succeeded and every manual item passed or carries a waiver."""
    reasons = []
    for c in cells:
        if not c.get("required"):
            continue
        bad = {k: v for k, v in c["verdicts"].items() if v != PASS}
        if bad:
            reasons.append(f"{'/'.join(c['key'])}: {bad}")
    reasons.sort(key=lambda s: (NOT_RUN not in s, NOT_MEASURED not in s, s))
    if not tier2_ok:
        reasons.append("tier 2: a required run did not succeed")
    for client, m in manual.items():
        if m["blocking"]:
            reasons.append(f"manual {client}: FAIL without a waiver: {m['blocking']}")
        if m["unwaived_not_run"]:
            reasons.append(f"manual {client}: not run: {m['unwaived_not_run']}")
    return (BAR_MET if not reasons else BAR_NOT_MET), reasons


def summarise(
    label: str,
    records: Sequence[Mapping[str, Any]],
    rejected: Sequence[Mapping[str, Any]],
    bar: Mapping[str, Any],
    goals_approved: bool,
    playbook_of: Mapping[str, str],
    suites: Sequence[str],
    baseline: Sequence[Mapping[str, Any]] = (),
    reference_calls: Mapping[str, int] | None = None,
    live: Sequence[Mapping[str, Any]] = (),
    tier2_ok: bool = True,
    manual: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    headings = []
    if not goals_approved:
        headings.append("GOALS NOT APPROVED")
    if bar.get("status") != "confirmed":
        headings.append(PROVISIONAL)
    groups: dict[CellKey, list[Mapping[str, Any]]] = {}
    for r in records:
        groups.setdefault(cell_key(r, playbook_of), []).append(r)
    required = {(c["playbook"], c["client"], c["tier"]) for c in bar["cells"]}
    for pb, client, tier in required:
        for surface in ("miassist",):
            groups.setdefault((pb, client, surface, tier), [])
    base_groups: dict[tuple[str, str, str], list[Mapping[str, Any]]] = {}
    for r in baseline:
        k = cell_key(r, playbook_of)
        base_groups.setdefault((k[0], k[1], k[3]), []).append(r)
    live_groups: dict[tuple[str, str], list[Mapping[str, Any]]] = {}
    for r in live:
        k = cell_key(r, playbook_of)
        live_groups.setdefault((k[0], k[1]), []).append(r)
    cells = []
    comparisons = []
    for key, recs in sorted(groups.items()):
        pb, client, surface, tier = key
        cell: dict[str, Any] = {
            "key": list(key),
            "attempts": len(recs),
            "valid": len([r for r in recs if r["outcome"] != classes.INVALID]),
            "required": (pb, client, tier) in required and surface == "miassist",
        }
        ten = first10(recs)
        ok = sum(r["outcome"] == classes.SUCCESS for r in ten)
        cell["successes"] = ok
        cell["wilson_95_informational"] = wilson(ok, len(ten))
        bars = [r["calls"]["bar_calls"] for r in ten]
        cell["bar_calls"] = {
            "median": median(bars),
            "min": min(bars) if bars else None,
            "max": max(bars) if bars else None,
        }
        cell["stuck"] = dict(
            sorted(
                {
                    c: sum(1 for r in ten if r.get("cls") == c)
                    for c in {r.get("cls") for r in ten if r.get("cls")}
                }.items()
            )
        )
        cell["invalid"] = [
            {"run_id": r["run_id"], "cls": r.get("cls")}
            for r in recs
            if r["outcome"] == classes.INVALID
        ]
        versions = {json.dumps([r["client"], r["model"], r["apps"]], sort_keys=True) for r in recs}
        cell["versions"] = [json.loads(v) for v in sorted(versions)]
        if surface == "baseline":
            cell["coverage"] = coverage(recs)
            cell["live_recordings"] = len(live_groups.get((pb, client), []))
            if (pb, client) in live_groups:
                cell["live"] = live_row(live_groups[(pb, client)], cell["bar_calls"]["median"])
                cell["live"]["agreement"] = [
                    {"run_id": lr["run_id"], "flag": tier_agreement(lr, recs)}
                    for lr in live_groups[(pb, client)]
                ]
        base = base_groups.get((pb, client, tier), [])
        med, basis = baseline_median(base, (reference_calls or {}).get(pb))
        if base and ten:
            why = comparable(ten[0], first10(base)[0]) if first10(base) else None
            comparisons.append(
                {"cell": list(key), "comparable": why is None, "why": why, "baseline_basis": basis}
            )
            if why is not None:
                med = None
        cell["baseline_basis"] = basis
        cell["verdicts"] = (
            verdicts(recs, bar, med)
            if goals_approved
            else {"success": NO_VERDICT, "calls": NO_VERDICT, "time": NO_VERDICT}
        )
        cells.append(cell)
    man = manual_summary(manual or {})
    if goals_approved:
        verdict, reasons = release_verdict(cells, tier2_ok, man)
    else:
        verdict, reasons = NO_VERDICT, ["the goal set is not approved (FR-002.6)"]
    summary = {
        "schema": "miassist.eval-report/v1",
        "label": label,
        "generated_utc": datetime.now(UTC).isoformat(),
        "headings": headings,
        "verdict": verdict,
        "reasons": reasons,
        "cells": cells,
        "rejected": list(rejected),
        "comparisons": comparisons,
        "manual": man,
        "suites": list(suites),
    }
    schemas.validate("eval-report", summary)
    return summary


def render(summary: Mapping[str, Any]) -> str:
    """REPORT.md from summary.json only (TD-8). Times in ET."""
    when = datetime.fromisoformat(summary["generated_utc"])
    lines = [f"# Evaluation report {summary['label']}", ""]
    lines += [f"**{h}**" for h in summary["headings"]]
    lines += ["", f"Generated {to_et(when)}. Verdict: **{summary['verdict']}**", ""]
    for reason in summary.get("reasons", []):
        lines.append(f"- {reason}")
    lines += [
        "",
        "| Cell | Attempts | Valid | Successes | Bar-calls median | Success | Calls | Time |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for c in summary["cells"]:
        v = c["verdicts"]
        lines.append(
            f"| {' / '.join(c['key'])} | {c['attempts']} | {c['valid']} | {c['successes']} | "
            f"{c['bar_calls']['median']} | {v['success']} | {v['calls']} | {v['time']} |"
        )
        if "coverage" in c:
            cov = c["coverage"]
            lines.append(
                f"|  coverage {cov['coverage']} {cov['flag'] or ''} | | | "
                f"{cov['success_off_recording_as_failure']} / "
                f"{cov['success_on_recording_only']} | off-recording {cov['off_recording']} | | | |"
            )
    if summary["rejected"]:
        lines += ["", "## Rejected runs", ""]
        lines += [f"- {r['run_id']}: {r['reason']}" for r in summary["rejected"]]
    lines += [
        "",
        "## Method",
        "",
        "Tier 1 replays recorded app answers: it measures the server under test against the "
        "recording, not against today's apps. A cassette miss is a failure on the miAssist "
        "surface; the baseline shows its coverage beside two success figures. Comparisons are "
        "made only within one tier, client, served model and goal set. The Wilson intervals are "
        "informational; the verdict uses the bar's counts. Doctoring is detectable for cassette "
        "files (manifest and append-only index) and run artifacts (hashes in each record), not "
        "for a record rewritten together with its artifacts before commit.",
        "",
    ]
    return "\n".join(lines)


def write(out_dir: Path, summary: Mapping[str, Any]) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=1, sort_keys=True) + "\n")
    (out_dir / "REPORT.md").write_text(render(summary))


#: The publication allow-list (FR-002.47, M14): figures only.
PUBLISH_FIELDS = {
    "top": ("schema", "label", "generated_utc", "headings", "verdict"),
    "cell": (
        "key",
        "attempts",
        "valid",
        "successes",
        "bar_calls",
        "stuck",
        "verdicts",
        "baseline_basis",
        "versions",
    ),
}


def publish(summary: Mapping[str, Any]) -> dict[str, Any]:
    out = {k: summary[k] for k in PUBLISH_FIELDS["top"] if k in summary}
    out["cells"] = [{k: c[k] for k in PUBLISH_FIELDS["cell"] if k in c} for c in summary["cells"]]
    return out
