"""One run record from the four logs (FR-002.21, FR-002.25-FR-002.29; FTID §3.7). Pure: files in,
a record out; never mocked (FTID §8.3)."""

from __future__ import annotations

import json
import statistics
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from miassist_eval import classes, effects, schemas
from miassist_eval.canonical import sha256_file

ARTIFACTS = ("transcript", "tap_log", "effects_log", "clock")
PRECEDENCE = (
    classes.AGENT_ATTEMPTED_DECISION,
    classes.UNGATED_GPU_START,
    classes.GPU_LIST_INCOMPLETE,
    classes.FORBIDDEN_ROUTE,
    classes.FIXTURE_NOT_ALLOWED,
    classes.FOREIGN_ID,
    classes.UNFILTERED_LIST,
    classes.TEXT_ANSWER_REFUSED,
    classes.GPU_LIST_DRIFT,
    classes.UNKNOWN_ROUTE,
    classes.MISSING_AGENT_HEADER,
    classes.OFF_RECORDING,
    classes.TURN_LIMIT,
    classes.TIME_LIMIT,
)


def verify_artifacts(record: Mapping[str, Any], run_dir: Path) -> str | None:
    """FR-002.29: every artifact exists and matches its sha256, else the reason it is rejected."""
    for name in ARTIFACTS:
        art = record.get("artifacts", {}).get(name)
        if not art:
            return f"{name}: not in the record"
        path = run_dir / art["path"]
        if not path.is_file():
            return f"{name}: {art['path']} is missing"
        if sha256_file(path) != art["sha256"]:
            return f"{name}: {art['path']} was altered"
    return None


def stuck_class(tap_log: Sequence[Mapping[str, Any]]) -> str:
    """The most specific class the tap log shows (FR-002.25)."""
    calls = [c for c in tap_log if c.get("method") == "tools/call"]
    streak = 1
    for prev, cur in zip(calls, calls[1:], strict=False):
        same = (prev.get("tool"), prev.get("args_sha256")) == (
            cur.get("tool"),
            cur.get("args_sha256"),
        )
        streak = streak + 1 if same and prev.get("is_error") and cur.get("is_error") else 1
        if streak >= 3:
            return classes.WRONG_TOOL_LOOP
    if calls and calls[-1].get("is_error"):
        return classes.ARGUMENT_REFUSAL
    return classes.ASKED_AND_STOPPED


def outcome(
    infra: str | None,
    failures: Sequence[tuple[str, str]],
    reached: Sequence[str],
    required: Sequence[str],
    final_check: str | None,
    tap_log: Sequence[Mapping[str, Any]],
    step_errors: int = 0,
    shape_errors: int = 0,
) -> tuple[str, str | None]:
    """The precedence of FTID §3.7: invalid causes, then the run failures in order, then limits,
    then a milestone shortfall, then the final message, then success. A cassette miss is a
    failure (``off_recording``), never invalid."""
    if infra is not None:
        return classes.INVALID, infra
    seen = {cls for cls, _ in failures}
    for cls in PRECEDENCE:
        if cls in seen:
            return classes.FAILED, cls
    if shape_errors:
        return classes.FAILED, classes.RESULT_SHAPE
    if step_errors:
        return classes.FAILED, classes.STEP_ERROR
    if any(m not in reached for m in required):
        return classes.FAILED, stuck_class(tap_log)
    if final_check is not None:
        return classes.FAILED, final_check
    return classes.SUCCESS, None


def calls_summary(tap_log: Sequence[Mapping[str, Any]], polls: int) -> dict[str, Any]:
    calls = [c for c in tap_log if c.get("method") == "tools/call"]
    by_tool = Counter(str(c.get("tool")) for c in calls)
    return {
        "total": len(calls),
        "bar_calls": len(calls) - polls,
        "polls": polls,
        "errors": sum(1 for c in calls if c.get("is_error")),
        "by_tool": dict(by_tool),
    }


def tool_choice(tap_log: Sequence[Mapping[str, Any]], expected: Sequence[str]) -> dict[str, Any]:
    calls = [str(c.get("tool")) for c in tap_log if c.get("method") == "tools/call"]
    on = [c for c in calls if c in set(expected)]
    return {
        "first_tool": calls[0] if calls else None,
        "on_path_share": (len(on) / len(calls)) if calls else None,
        "off_path": [c for c in calls if c not in set(expected)],
    }


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]


def median(values: Sequence[float]) -> float | None:
    return statistics.median(values) if values else None


def build_record(
    meta: Mapping[str, Any],
    run_dir: Path,
    goal: Mapping[str, Any],
    profiles: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    """Score one run directory. ``meta`` holds the driver's metadata (client, model, versions,
    tokens, wall times, failures, infra cause, final message check)."""
    tap_log = read_jsonl(run_dir / meta["artifacts"]["tap_log"]["path"])
    eff = read_jsonl(run_dir / meta["artifacts"]["effects_log"]["path"])
    start, end = float(meta["time"]["start"]), float(meta["time"]["end"])
    reached = effects.milestones(eff, goal)
    wait_list = effects.waits(eff, profiles, end)
    polls = effects.poll_calls(tap_log, eff, profiles, wait_list)
    names = [m for m, _ in reached]
    first_useful = dict(reached).get(goal["first_useful_result"])
    out, cls = outcome(
        meta.get("infra"),
        [tuple(f) for f in meta.get("failures", [])],
        names,
        goal["required"],
        meta.get("final_check"),
        tap_log,
        int(meta.get("step_errors", 0)),
        int(meta.get("shape_errors", 0)),
    )
    record = {
        **{
            k: meta[k]
            for k in (
                "schema",
                "run_id",
                "suite_id",
                "attempt",
                "surface",
                "tier",
                "client",
                "model",
                "server_under_test",
                "apps",
                "harness_version",
                "cassette",
                "goal",
                "tokens",
                "user_nudges",
                "reference_stale",
                "artifacts",
            )
        },
        "outcome": out,
        "cls": cls,
        "milestones_reached": [{"id": m, "t": t} for m, t in reached],
        "stuck_at": (
            None
            if out != classes.FAILED
            else {"last_milestone": names[-1] if names else None, "cls": cls}
        ),
        "calls": calls_summary(tap_log, polls),
        "tool_choice": tool_choice(tap_log, meta.get("expected_path", [])),
        "time": {
            "wall_s": end - start,
            "waits": [{"kind": k, "start": s, "end": e} for k, s, e in wait_list],
            "active_s": effects.active_time(start, end, wait_list),
            "first_useful_active_s": (
                None
                if first_useful is None
                else effects.active_until(first_useful, start, wait_list)
            ),
        },
        "operator_handoffs": int(meta.get("operator_handoffs", 0)),
        "limits": meta.get("limits", {}),
        "budget_stop": bool(meta.get("budget_stop", False)),
    }
    schemas.validate("eval-run", record)
    return record
