"""Paid-run budget and the CI refusal (M13; FTID §7.3; FR-002.16a)."""

from __future__ import annotations

import os
import statistics
from collections.abc import Mapping, Sequence

from miassist_eval import classes
from miassist_eval.classes import Refusal

PAID_TIERS = frozenset({"1b", "2"})


def in_ci(env: Mapping[str, str] | None = None) -> bool:
    env = os.environ if env is None else env
    return bool(env.get("CI")) or bool(env.get("GITHUB_ACTIONS"))


def refuse_paid_in_ci(tier: str, env: Mapping[str, str] | None = None) -> None:
    """Tier 1b and tier 2 run only by hand on the operator's workstation, never in CI (M13)."""
    if tier in PAID_TIERS and in_ci(env):
        raise Refusal(classes.CI_REFUSED, f"tier {tier} never runs in CI (M13)")


def estimate(planned: int, last_costs: Sequence[float], per_run_ceiling: float | None) -> float:
    if last_costs:
        return planned * statistics.median(last_costs)
    if per_run_ceiling is None:
        raise Refusal(classes.BUDGET_EXCEEDED, "no recorded cost and no per-run ceiling")
    return planned * per_run_ceiling


def check_start(
    tier: str,
    planned: int,
    budget_usd: float | None,
    last_costs: Sequence[float],
    per_run_ceiling: float | None,
) -> float:
    if tier not in PAID_TIERS:
        return 0.0
    if budget_usd is None:
        raise Refusal(classes.BUDGET_EXCEEDED, f"a tier-{tier} suite needs --budget-usd")
    cost = estimate(planned, last_costs, per_run_ceiling)
    if cost > budget_usd:
        raise Refusal(classes.BUDGET_EXCEEDED, f"estimate {cost:.2f} USD over {budget_usd:.2f}")
    return cost


def may_start_next(spent: float, next_estimate: float, budget_usd: float | None) -> bool:
    return budget_usd is None or spent + next_estimate <= budget_usd
