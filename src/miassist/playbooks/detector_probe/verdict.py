"""The verdict: numbers from the report, words from guidance (003 FPRD FR-003.17, FR-003.18, §4.2;
FTID §3.4). ``facts`` is pure arithmetic over the report's blocks; ``render`` picks templates from
``guidance/playbooks/detector-probe.yaml`` (``verdict.*``). Names of sets are app text and stay in
``data``; the words refer to sets by role (FPRD §4.5)."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

Say = Callable[..., str]


@dataclass(frozen=True)
class VerdictFacts:
    rung: int
    ood_sets: list[dict[str, Any]] = field(default_factory=list)
    everyday_sets: list[dict[str, Any]] = field(default_factory=list)
    nonsense_sets: list[dict[str, Any]] = field(default_factory=list)
    not_counted: list[str] = field(default_factory=list)
    auroc_ci_low: float | None = None
    app_next_step: str = ""
    shared_split: bool = False

    def as_data(self) -> dict[str, Any]:
        return {
            "rung": self.rung,
            "ood_sets": self.ood_sets,
            "everyday_sets": self.everyday_sets,
            "nonsense_sets": self.nonsense_sets,
            "auroc_ci_low": self.auroc_ci_low,
            "app_next_step": self.app_next_step[:300],
        }


def _sets(block: Any) -> list[Mapping[str, Any]]:
    if not isinstance(block, Mapping):
        return []
    return [s for s in block.get("sets") or [] if isinstance(s, Mapping)]


def _alarms(block: Any, not_counted: list[str]) -> list[dict[str, Any]]:
    out = []
    for s in _sets(block):
        if not s.get("counts"):
            if s.get("note"):
                not_counted.append(str(s["note"])[:200])
            continue
        rows = int(s.get("rows") or 0)
        alarms = int(s.get("false_alarms") or 0)
        allowed = s.get("allowed")
        out.append(
            {
                "name": str(s.get("name", ""))[:200],
                "rows": rows,
                "false_alarms": alarms,
                "per_1000": round(alarms / rows * 1000, 1) if rows else None,
                "allowed_per_1000": (
                    round(int(allowed) / rows * 1000, 1) if rows and allowed is not None else None
                ),
            }
        )
    return out


def facts(report: Mapping[str, Any], *, shared_split: bool = False) -> VerdictFacts:
    probe = report.get("probe") if isinstance(report.get("probe"), Mapping) else {}
    not_counted: list[str] = []
    ood = []
    for s in _sets(report.get("catch_rate")):
        positives = int(s.get("positives") or 0)
        caught = int(s.get("caught") or 0)
        if not positives:
            if s.get("note"):
                not_counted.append(str(s["note"])[:200])
            continue
        ood.append(
            {
                "name": str(s.get("name", ""))[:200],
                "caught": caught,
                "positives": positives,
                "rate": round(caught / positives * 100),
                "needed": s.get("needed"),
            }
        )
    lows = []
    for e in report.get("evaluations") or []:
        metrics = e.get("metrics") if isinstance(e, Mapping) else None
        ci = metrics.get("ci") if isinstance(metrics, Mapping) and metrics.get("scored") else None
        if isinstance(ci, Mapping) and isinstance(ci.get("low"), int | float):
            lows.append(float(ci["low"]))
    return VerdictFacts(
        rung=int((probe or {}).get("rung") or 0),
        ood_sets=ood,
        everyday_sets=_alarms(report.get("everyday_text"), not_counted),
        nonsense_sets=_alarms(report.get("nonsense_text"), not_counted),
        not_counted=not_counted,
        auroc_ci_low=round(min(lows), 3) if lows else None,
        app_next_step=str(report.get("rung_next_step") or ""),
        shared_split=shared_split,
    )


def render(f: VerdictFacts, say: Say) -> str:
    """The beginner narrative (``explain``): headline, the numbers, the next step."""
    rung = min(max(f.rung, 0), 3)
    parts = [say(f"verdict.r{rung}")]
    for s in f.ood_sets:
        parts.append(
            say(
                "verdict.ood_line",
                rate=s["rate"],
                caught=s["caught"],
                positives=s["positives"],
                needed=s["needed"],
            )
        )
    if not f.ood_sets and rung <= 1:
        parts.append(say("verdict.no_ood"))
    for s in f.everyday_sets:
        parts.append(
            say(
                "verdict.everyday_line",
                per_thousand=s["per_1000"],
                allowed_per_thousand=s["allowed_per_1000"],
            )
        )
    for s in f.nonsense_sets:
        parts.append(
            say(
                "verdict.nonsense_line",
                per_thousand=s["per_1000"],
                allowed_per_thousand=s["allowed_per_1000"],
            )
        )
    for note in f.not_counted:
        parts.append(say("verdict.not_counted", note=note))
    if f.auroc_ci_low is not None:
        parts.append(say("verdict.auroc_line", low=f.auroc_ci_low))
    if rung >= 2:
        parts.append(say("verdict.ready"))
    if f.shared_split:
        parts.append(say("verdict.caveat"))
    parts.append(say(f"verdict.next.r{rung}"))
    return " ".join(parts)


def expert_line(f: VerdictFacts, say: Say) -> str:
    """``data.summary`` at both levels (FPRD §4.2 expert line)."""
    ood = ", ".join(f"{s['rate']}% ({s['caught']}/{s['positives']})" for s in f.ood_sets) or "-"
    everyday = (
        ", ".join(f"{s['per_1000']}/1k (≤ {s['allowed_per_1000']}/1k)" for s in f.everyday_sets)
        or "-"
    )
    nonsense = ", ".join(f"{s['per_1000']}/1k" for s in f.nonsense_sets) or "-"
    nxt = "miassist_detector_deploy" if f.rung >= 2 else "miassist_detector_data"
    low = f.auroc_ci_low if f.auroc_ci_low is not None else "-"
    return say(
        "verdict.expert",
        rung=f.rung,
        ood=ood,
        everyday=everyday,
        nonsense=nonsense,
        low=low,
        next=nxt,
    )
