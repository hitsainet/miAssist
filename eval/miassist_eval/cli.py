"""``python -m miassist_eval <command>`` (FTDD §5.1). Exit codes: 0 success; 1 a run or verdict
failed; 2 refused before running; 3 harness error or a command whose task has not landed."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from miassist_eval import (
    allowed,
    budget,
    cassette,
    classes,
    gpu_guard,
    openapi_ref,
    report,
    schemas,
    staleness,
)
from miassist_eval.classes import Refusal

EVAL_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = EVAL_ROOT.parent
BAR_PATH = EVAL_ROOT / "bar.yaml"
NOT_LANDED = 3


def _say(text: str) -> None:
    print(text, flush=True)


def _refused(refusal: Refusal) -> int:
    _say(f"REFUSED {refusal}")
    return 2


def entry_checks(surface: str, goal_id: str | None = None) -> None:
    """FR-002.35a (R3M-4): what ``record`` and ``gap-record`` need from Core, in turn: the vendored
    vectors (``gpu_list_missing`` on EVERY surface), Core's fixture-filter module
    (``filter_module_missing``, whatever MIASSIST_REQUIRE_CORE says) and Core's cassette schema
    (``cassette_schema_missing``). With a goal, on the miAssist surface, every GPU start the goal
    needs must be in the derived list (``gpu_list_incomplete``; R1 review fix OR1-002-4,
    2026-11-16: "no live miAssist recording of the steering goal" is this refusal, not a note)."""
    profile = yaml.safe_load((EVAL_ROOT / "route_profiles" / "miworkbench.yaml").read_text())
    gpu = gpu_guard.load(openapi_ref.load("miworkbench"), profile.get("gpu_arms"))
    if goal_id is not None:
        from miassist_eval import goals

        playbook = str(goals.load().goal(goal_id).get("playbook_id"))
        gpu_guard.refuse_incomplete_goal(playbook, gpu, surface)
    allowed.require_core()
    schemas.core_cassette_schema()


def cmd_record(args: argparse.Namespace) -> int:
    try:
        budget.refuse_paid_in_ci("2")
        entry_checks(args.surface, getattr(args, "goal", None))
    except Refusal as refusal:
        return _refused(refusal)
    if not os.environ.get("MIASSIST_EVAL_LIVE_APPS") and not args.live_apps:
        _say(
            "REFUSED record runs only by hand on the workstation against live apps "
            "(MIASSIST_EVAL_LIVE_APPS); nothing was recorded"
        )
        return 2
    _say("record: the live recording run is FTASKS 8.3 / 10.3 (operator, by hand)")
    return NOT_LANDED


def cmd_gap_record(args: argparse.Namespace) -> int:
    return cmd_record(argparse.Namespace(surface="baseline", live_apps=args.live_apps))


def cmd_run(args: argparse.Namespace) -> int:
    try:
        budget.refuse_paid_in_ci(args.tier)
    except Refusal as refusal:
        return _refused(refusal)
    _say(
        "run: the server-under-test factories land with FTASKS 5.2/5.3 (baseline images, "
        "miAssist server); tier 1a's machinery is miassist_eval.suite"
    )
    return NOT_LANDED


def cmd_verify(args: argparse.Namespace) -> int:
    if args.live_apps:
        _say("REFUSED --live-apps is a workstation step (FTASKS 11.2)")
        return 2
    refs = {a: openapi_ref.load(a) for a in openapi_ref.APPS}
    takes = cassette.find_takes()
    if not takes:
        _say(f"no takes under {cassette.EVAL_CASSETTES}")
        return 0
    try:
        for take_dir in takes:
            take = cassette.load(take_dir)
            hashes = {a: v["openapi_sha256"] for a, v in take.manifest["apps"].items()}
            staleness.refuse_if_stale(staleness.check_cassette(take.cassette, refs, hashes))
            _say(f"ok {take.cassette_id}")
    except Refusal as refusal:
        return _refused(refusal)
    return 0


def cmd_report(args: argparse.Namespace) -> int:
    from miassist_eval import goals, score

    records, rejected = [], []
    for suite_id in args.suite_ids:
        suite_dir = EVAL_ROOT / "runs" / suite_id
        for path in sorted(suite_dir.glob("r-*/record.json")):
            record = json.loads(path.read_text())
            why = score.verify_artifacts(record, path.parent)
            if why:
                rejected.append({"run_id": record["run_id"], "reason": why})
            else:
                records.append(record)
    gs = goals.load()
    bar = yaml.safe_load(BAR_PATH.read_text())
    summary = report.summarise(
        args.label or "+".join(args.suite_ids),
        records,
        rejected,
        bar,
        gs.approved,
        {g["id"]: g["playbook_id"] for g in gs.goals},
        args.suite_ids,
    )
    report.write(EVAL_ROOT / "runs" / "reports" / summary["label"], summary)
    _say(f"{summary['verdict']}: {len(records)} runs, {len(rejected)} rejected")
    return 0 if summary["verdict"] == report.BAR_MET else 1


def cmd_bar_confirm(args: argparse.Namespace) -> int:
    """Run only on the operator's instruction (FR-002.33): validates the baseline report and its
    goal-set hash, prints the diff and needs --yes."""
    from miassist_eval import goals

    summary_path = Path(args.baseline) / "summary.json"
    if not summary_path.is_file():
        _say(f"REFUSED no baseline report at {summary_path}")
        return 2
    gs = goals.load()
    bar = yaml.safe_load(BAR_PATH.read_text())
    new = {
        **bar,
        "status": "confirmed",
        "confirmed_on": datetime.now(UTC).date().isoformat(),
        "words": args.words,
        "baseline_report": str(args.baseline),
        "baseline_goal_set_sha256": gs.sha256,
    }
    found = schemas.errors("bar", new)
    if found:
        _say("REFUSED " + "; ".join(found))
        return 2
    _say(json.dumps({"before": bar, "after": new}, indent=1, default=str))
    if not args.yes:
        _say("not written: --yes is required")
        return 2
    BAR_PATH.write_text(yaml.safe_dump(new, sort_keys=False))
    return 0


def cmd_manual_new(args: argparse.Namespace) -> int:
    checklist = REPO_ROOT / "0xcc" / "evaluation" / "MANUAL_CHECK.md"
    ids = (
        [ln.split("`")[1] for ln in checklist.read_text().splitlines() if ln.startswith("- [ ] `")]
        if checklist.is_file()
        else []
    )
    doc = {
        "schema": "miassist.eval-manual/v1",
        "release": args.release,
        "client": args.client,
        "items": [
            {"id": i, "result": "not_run", "reason": "not yet checked", "waiver": None} for i in ids
        ],
    }
    schemas.validate("eval-manual", doc)
    out = REPO_ROOT / "0xcc" / "evaluation" / "manual" / args.release / f"{args.client}.yaml"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(yaml.safe_dump(doc, sort_keys=False))
    _say(str(out))
    return 0


def cmd_publish(args: argparse.Namespace) -> int:
    src = Path(args.report_dir) / "summary.json"
    summary = json.loads(src.read_text())
    published = report.publish(summary)
    (src.parent / "published.json").write_text(json.dumps(published, indent=1, sort_keys=True))
    lines = [
        f"# miAssist evaluation: {published.get('label')}",
        "",
        f"Verdict: **{published.get('verdict')}**",
        "",
    ]
    lines += [
        f"- {' / '.join(c['key'])}: {c.get('successes')}/{c.get('valid')} successful, "
        f"median bar-calls {c.get('bar_calls', {}).get('median')}"
        for c in published["cells"]
    ]
    (src.parent / "PUBLISHED.md").write_text("\n".join(lines) + "\n")
    return 0


def cmd_not_landed(name: str) -> Any:
    def run(args: argparse.Namespace) -> int:
        _say(f"{name}: needs live apps on the workstation (FTASKS 3.2b, 4.6d); not run here")
        return 2 if not os.environ.get("MIASSIST_EVAL_LIVE_APPS") else NOT_LANDED

    return run


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m miassist_eval")
    sub = p.add_subparsers(dest="command", required=True)
    s = sub.add_parser("lint")
    s.add_argument("--surface", choices=["miassist", "baseline"], default="miassist")
    s.set_defaults(fn=lambda a: NOT_LANDED)
    s = sub.add_parser("record")
    s.add_argument("--goal", required=True)
    s.add_argument("--surface", choices=["miassist", "baseline"], required=True)
    s.add_argument("--client", default="claude_code")
    s.add_argument("--live-apps")
    s.set_defaults(fn=cmd_record)
    s = sub.add_parser("gap-record")
    s.add_argument("--cassette", required=True)
    s.add_argument("--misses", required=True)
    s.add_argument("--live-apps")
    s.set_defaults(fn=cmd_gap_record)
    s = sub.add_parser("fixtures")
    s.add_argument("action", choices=["create", "check"])
    s.set_defaults(fn=cmd_not_landed("fixtures"))
    s = sub.add_parser("fairness")
    s.add_argument("--goal", required=True)
    s.set_defaults(fn=cmd_not_landed("fairness"))
    s = sub.add_parser("run")
    s.add_argument("--tier", choices=["1a", "1b", "2"], required=True)
    s.add_argument("--surface", choices=["miassist", "baseline"], default="miassist")
    s.add_argument("--client", default="scripted")
    s.add_argument("--goals", default="")
    s.add_argument("--runs", type=int, default=1)
    s.add_argument("--budget-usd", type=float)
    s.set_defaults(fn=cmd_run)
    s = sub.add_parser("verify-cassettes")
    s.add_argument("--live-apps")
    s.set_defaults(fn=cmd_verify)
    s = sub.add_parser("report")
    s.add_argument("suite_ids", nargs="+")
    s.add_argument("--baseline")
    s.add_argument("--release")
    s.add_argument("--label")
    s.set_defaults(fn=cmd_report)
    s = sub.add_parser("bar")
    s.add_argument("action", choices=["confirm"])
    s.add_argument("--baseline", required=True)
    s.add_argument("--words", required=True)
    s.add_argument("--yes", action="store_true")
    s.set_defaults(fn=cmd_bar_confirm)
    s = sub.add_parser("manual")
    s.add_argument("action", choices=["new"])
    s.add_argument("--release", required=True)
    s.add_argument("--client", choices=["desktop", "claude-ai"], required=True)
    s.set_defaults(fn=cmd_manual_new)
    s = sub.add_parser("publish")
    s.add_argument("report_dir")
    s.set_defaults(fn=cmd_publish)
    return p


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        code: int = args.fn(args)
        return code
    except Refusal as refusal:
        return _refused(refusal)
    except Exception as exc:  # noqa: BLE001
        _say(f"{classes.HARNESS_ERROR}: {exc!r}")
        return 3


if __name__ == "__main__":
    sys.exit(main())
