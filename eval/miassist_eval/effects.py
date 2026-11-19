"""The effects log, milestones and waits (FR-002.7, FR-002.25, FR-002.26; FTID §3.5; TD-5).

The log comes from the replay server (tier 1) or the recorder (tier 2 and recordings): one line per
REST request the server under test made, in order, on one monotonic clock.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from miassist_eval.canonical import sha256


@dataclass
class EffectsLog:
    lines: list[dict[str, Any]] = field(default_factory=list)

    def append(self, **line: Any) -> dict[str, Any]:
        if "request_body" in line:
            body = line.pop("request_body")
            line["request_body_sha256"] = sha256(body)
        self.lines.append(line)
        return line

    def write(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as fh:
            for line in self.lines:
                fh.write(json.dumps(line, sort_keys=True, default=str) + "\n")

    @staticmethod
    def read(path: Path) -> list[dict[str, Any]]:
        return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]


def _get(obj: Any, dotted: str) -> Any:
    node = obj
    for part in dotted.split("."):
        if not isinstance(node, Mapping):
            return None
        node = node.get(part)
    return node


def predicate_holds(pred: Mapping[str, Any], line: Mapping[str, Any]) -> bool:
    status = pred.get("status")
    if status is not None:
        allowed = status if isinstance(status, list) else [status]
        if line.get("status") not in allowed:
            return False
    body = line.get("answer")
    for dotted, values in (pred.get("json") or {}).items():
        if _get(body, dotted) not in values:
            return False
    for dotted in pred.get("nonempty") or []:
        value = _get(body, dotted)
        if value in (None, "", [], {}):
            return False
    for name, values in (pred.get("request_query_not") or {}).items():
        got = (line.get("query") or {}).get(name)
        if got is not None and str(got).lower() in {str(v).lower() for v in values}:
            return False
    return True


def milestones(
    effects: Iterable[Mapping[str, Any]], goal: Mapping[str, Any]
) -> list[tuple[str, float]]:
    """Milestones reached, in the order reached, each at its first qualifying line; ``after`` is
    honoured (the milestone counts only once the named one was reached earlier)."""
    reached: dict[str, float] = {}
    for line in effects:
        if line.get("refused"):
            continue
        for m in goal["milestones"]:
            if m["id"] in reached:
                continue
            for alt in m["any_of"]:
                if (alt["app"], alt["method"], alt["route"]) != (
                    line.get("app"),
                    line.get("method"),
                    line.get("route"),
                ):
                    continue
                if alt.get("after") and alt["after"] not in reached:
                    continue
                if predicate_holds(alt["predicate"], line):
                    reached[m["id"]] = float(line.get("t_mono", 0.0))
                    break
    return sorted(reached.items(), key=lambda kv: kv[1])


Interval = tuple[float, float]


def waits(
    effects: Sequence[Mapping[str, Any]],
    profiles: Mapping[str, Mapping[str, Any]],
    end: float,
    gpu_actions: set[str] | None = None,
) -> list[tuple[str, float, float]]:
    """GPU, approval and hand-off waits read from status reads (FR-002.26). An object still open at
    the end of the log waits until ``end``."""
    opened: dict[tuple[str, str, str], float] = {}
    out: list[tuple[str, float, float]] = []
    entries = {
        (app, r["method"], r["route"]): r
        for app, prof in profiles.items()
        for r in prof.get("routes", [])
        if r.get("poll_of")
    }
    for line in effects:
        app, t = str(line.get("app")), float(line.get("t_mono", 0.0))
        if line.get("refused") == "operator_handoff":
            key = (app, "handoff", str(line.get("route")))
            opened.setdefault(key, t)
            continue
        if line.get("handoff_done"):
            for key in [k for k in opened if k[1] == "handoff"]:
                out.append(("handoff", opened.pop(key), t))
            continue
        entry = entries.get((app, str(line.get("method")), str(line.get("route"))))
        if entry is None:
            continue
        state = _get(line.get("answer"), entry.get("state_field", "status"))
        obj = (app, entry["poll_of"], str(line.get("path")))
        kind = "approval" if entry["poll_of"] == "approval" else "gpu"
        if state in entry.get("open_states", []):
            opened.setdefault(obj, t)
        elif state in entry.get("run_states", []):
            if obj in opened:
                out.append((kind, opened.pop(obj), t))
            opened.setdefault((app, "run", str(line.get("path"))), t)
        elif state in entry.get("closed_states", []) or state in entry.get("done_states", []):
            if obj in opened:
                out.append((kind, opened.pop(obj), t))
            run_key = (app, "run", str(line.get("path")))
            if run_key in opened:
                start = opened.pop(run_key)
                if gpu_actions is None or line.get("gpu_work"):
                    out.append(("gpu", start, t))
    for key, start in opened.items():
        kind = "approval" if key[1] == "approval" else "handoff" if key[1] == "handoff" else "gpu"
        out.append((kind, start, end))
    return sorted(out, key=lambda w: (w[1], w[2]))


def merge(intervals: Iterable[Interval]) -> list[Interval]:
    merged: list[list[float]] = []
    for start, stop in sorted(intervals):
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], stop)
        else:
            merged.append([start, stop])
    return [(a, b) for a, b in merged]


def active_time(
    wall_start: float, wall_end: float, wait_list: Iterable[tuple[str, float, float]]
) -> float:
    clipped = [(max(s, wall_start), min(e, wall_end)) for _, s, e in wait_list]
    spans = merge((s, e) for s, e in clipped if e > s)
    return (wall_end - wall_start) - sum(e - s for s, e in spans)


def active_until(
    t: float, wall_start: float, wait_list: Iterable[tuple[str, float, float]]
) -> float:
    """Active time from the start of the run to ``t`` (the first useful result)."""
    return active_time(wall_start, t, wait_list)


def poll_calls(
    tap_log: Sequence[Mapping[str, Any]],
    effects: Sequence[Mapping[str, Any]],
    profiles: Mapping[str, Mapping[str, Any]],
    wait_list: list[tuple[str, float, float]],
) -> int:
    """Tool calls whose REST requests (between the call's request and answer times) are only
    status reads of objects with an open wait at that time (PE-4)."""
    polls = {
        (app, r["method"], r["route"])
        for app, prof in profiles.items()
        for r in prof.get("routes", [])
        if r.get("poll_of")
    }
    count = 0
    for call in tap_log:
        if call.get("method") != "tools/call":
            continue
        start, stop = float(call.get("t_mono", 0.0)), float(
            call.get("t_answer", call.get("t_mono", 0.0))
        )
        inside = [e for e in effects if start <= float(e.get("t_mono", 0.0)) <= stop]
        if not inside:
            continue
        if all((e.get("app"), e.get("method"), e.get("route")) in polls for e in inside) and all(
            any(s <= float(e.get("t_mono", 0.0)) <= w for _, s, w in wait_list) for e in inside
        ):
            count += 1
    return count
