"""The check verdict (004 FTDD §6 ``checks.py``; FTID §3.4; FPRD FR-004.13, FR-004.14).

Pure functions. One ``CheckLine`` per check C-1 to C-9: its outcome (``green``, ``note``,
``amber``, ``refused``, or ``not_run``, which counts as amber), the plain meaning from the playbook's
words at the person's level, and the evidence from the result's own fields, quoted. ``push_allowed``
is stated per visibility ONLY from a completed check run the operator started (A34), by
miDataworks' own rule (``services/publishing/checks.py`` ``push_allowed``, X-02): any refused
outcome refuses every push, any amber refuses a public push. Without a run it is ``None`` and no
"ready to publish" is ever said.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final

from miassist.playbooks._shared.calm import quote

CHECK_IDS: Final = ("C-1", "C-2", "C-3", "C-4", "C-5", "C-6", "C-7", "C-8", "C-9")
OUTCOMES: Final = ("green", "note", "amber", "refused")
NOT_RUN: Final = "not_run"
COMPLETE: Final = frozenset({"completed", "complete", "done", "succeeded"})

Words = Mapping[str, str]


@dataclass(frozen=True)
class CheckLine:
    id: str
    outcome: str
    plain: str
    evidence: str

    def as_dict(self) -> dict[str, str]:
        return {
            "id": self.id,
            "outcome": self.outcome,
            "plain": self.plain,
            "evidence": self.evidence,
        }


def licence_plain(words: Words, licence: str | None) -> str:
    """FTID I1: a licence id in plain words; an unknown one reads "read it before sharing"."""
    if licence:
        key = f"licence.{licence.lower()}"
        if key in words:
            return words[key]
    return words["licence.unknown"]


def _evidence(fields: Any) -> str:
    if not isinstance(fields, Mapping) or not fields:
        return ""
    parts = []
    for key in sorted(fields):
        value = fields[key]
        if isinstance(value, Mapping | list):
            continue
        parts.append(f"{key}={value}")
    return quote(", ".join(parts)) if parts else ""


def _plain(words: Words, check_id: str, level: str, fallback: str | None) -> str:
    key = f"check.{check_id.lower()}.{'expert' if level == 'expert' else 'beginner'}"
    if key in words:
        return words[key]
    # An unknown check id falls back to miDataworks' own text, quoted (FTASKS 4.4).
    return words["check.unknown"].replace("{text}", quote(fallback or check_id))


def run_complete(check_run: Any) -> bool:
    return isinstance(check_run, Mapping) and str(check_run.get("status", "")).lower() in COMPLETE


def leakage_pairs(report: Any) -> int | None:
    """The near-duplicate pair count of an existing leakage report (``report_out``), if stated."""
    if not isinstance(report, Mapping):
        return None
    result = report.get("result") if isinstance(report.get("result"), Mapping) else report
    for source in (result, result.get("summary") if isinstance(result, Mapping) else None):
        if isinstance(source, Mapping):
            for key in ("pair_count", "pairs_total", "cross_split_pairs", "pairs"):
                value = source.get(key)
                if isinstance(value, int) and not isinstance(value, bool):
                    return value
                if isinstance(value, list):
                    return len(value)
    return None


def shortcut_warnings(audit: Any) -> list[Mapping[str, Any]]:
    if not isinstance(audit, Mapping):
        return []
    warnings = audit.get("warnings")
    return [w for w in warnings if isinstance(w, Mapping)] if isinstance(warnings, list) else []


def verdict(
    words: Words,
    level: str,
    *,
    check_run: Any = None,
    leakage: Any = None,
    shortcut: Any = None,
) -> list[CheckLine]:
    """One line per check, C-1 to C-9 in order, then any other check the run reported."""
    lines: dict[str, CheckLine] = {}
    if run_complete(check_run):
        for item in check_run.get("results") or []:
            if not isinstance(item, Mapping):
                continue
            cid = str(item.get("check") or item.get("id") or "")
            outcome = str(item.get("outcome") or "")
            if not cid or outcome not in OUTCOMES:
                continue
            evidence = _evidence(item.get("evidence")) or quote(item.get("reason") or "")
            lines[cid] = CheckLine(
                cid, outcome, _plain(words, cid, level, str(item.get("reason") or "")), evidence
            )
    if "C-3" not in lines:
        pairs = leakage_pairs(leakage)
        if pairs is not None:
            outcome = "amber" if pairs > 0 else "green"
            lines["C-3"] = CheckLine(
                "C-3", outcome, _plain(words, "C-3", level, None), quote(f"pairs={pairs}")
            )
    if "C-7" not in lines and isinstance(shortcut, Mapping):
        found = shortcut_warnings(shortcut)
        evidence = _evidence(found[0]) if found else quote("warnings=0")
        lines["C-7"] = CheckLine(
            "C-7", "amber" if found else "green", _plain(words, "C-7", level, None), evidence
        )
    out = []
    for cid in CHECK_IDS:
        line = lines.pop(cid) if cid in lines else None
        out.append(line or CheckLine(cid, NOT_RUN, _plain(words, cid, level, None), ""))
    out += [lines[k] for k in sorted(lines) if k.startswith("C-")]
    return out


def counts(lines: Sequence[CheckLine]) -> dict[str, int]:
    out = dict.fromkeys((*OUTCOMES, NOT_RUN), 0)
    for line in lines:
        out[line.outcome] = out.get(line.outcome, 0) + 1
    return out


def push_allowed(check_run: Any) -> dict[str, bool] | None:
    """Per visibility, from a completed run's results only (X-02); ``None`` without one."""
    if not run_complete(check_run):
        return None
    outcomes = [
        str(i.get("outcome")) for i in check_run.get("results") or [] if isinstance(i, Mapping)
    ]
    refused = "refused" in outcomes
    amber = "amber" in outcomes
    return {"private": not refused, "public": not refused and not amber}
