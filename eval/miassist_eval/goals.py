"""Goals: load, validate, the goal-set hash and its approval state (FR-002.4, FR-002.6; FTDD §4.1)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from miassist_eval import schemas
from miassist_eval.canonical import sha256

EVAL_ROOT = Path(__file__).resolve().parents[1]
GOALS_PATH = EVAL_ROOT / "goals.yaml"
NOT_APPROVED = "GOALS NOT APPROVED"


@dataclass(frozen=True)
class GoalSet:
    raw: dict[str, Any]

    @property
    def goals(self) -> list[dict[str, Any]]:
        goals: list[dict[str, Any]] = self.raw["goals"]
        return goals

    @property
    def fixed_replies(self) -> dict[str, str]:
        replies: dict[str, str] = self.raw["fixed_replies"]
        return replies

    def goal(self, goal_id: str) -> dict[str, Any]:
        for g in self.goals:
            if g["id"] == goal_id:
                return g
        raise KeyError(goal_id)

    @property
    def sha256(self) -> str:
        """sha256 of the canonical JSON of ``goals`` and ``fixed_replies``, never ``approved``."""
        return goal_set_sha256(self.raw)

    @property
    def approved(self) -> bool:
        approval = self.raw.get("approved")
        return isinstance(approval, dict) and approval.get("goal_set_sha256") == self.sha256

    def headings(self) -> list[str]:
        return [] if self.approved else [NOT_APPROVED]


def goal_set_sha256(raw: dict[str, Any]) -> str:
    return sha256({"goals": raw["goals"], "fixed_replies": raw["fixed_replies"]})


def check(raw: dict[str, Any], fixture_keys: set[str] | None = None) -> list[str]:
    """Every problem with a goals document: schema, duplicate ids, milestone references, fixtures."""
    found = schemas.errors("eval-goals", raw)
    if found:
        return found
    ids = [g["id"] for g in raw["goals"]]
    found += [f"duplicate goal id {i}" for i in sorted({i for i in ids if ids.count(i) > 1})]
    for g in raw["goals"]:
        mids = [m["id"] for m in g["milestones"]]
        for name in [g["first_useful_result"], *g["required"]]:
            if name not in mids:
                found.append(f"{g['id']}: milestone {name} is not defined")
        for m in g["milestones"]:
            for alt in m["any_of"]:
                if alt.get("after") and alt["after"] not in mids:
                    found.append(f"{g['id']}: {m['id']} after unknown milestone {alt['after']}")
        if g["final_message_check"]["source_milestone"] not in mids:
            found.append(f"{g['id']}: final check names an unknown milestone")
        if fixture_keys is not None:
            found += [
                f"{g['id']}: fixture {f} is not in fixtures.yaml"
                for f in g["fixtures"]
                if f not in fixture_keys
            ]
    return found


def load(path: Path = GOALS_PATH, fixture_keys: set[str] | None = None) -> GoalSet:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    found = check(raw, fixture_keys)
    if found:
        raise ValueError("goals: " + "; ".join(found))
    return GoalSet(raw)
