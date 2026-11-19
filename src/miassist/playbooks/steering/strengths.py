"""Default sweep strengths (005 FTDD §6 ``strengths.py``; FPRD FR-005.11). Pure.

sign x ``[0.05, 0.10, 0.15, 0.25, 0.40]`` x the feature's own ``max_activation``, rounded to 2
decimals, each capped at |300| (miWorkbench's ``ProfileMember.strength`` bound). A missing or
non-positive ``max_activation`` is not a real scale: ``NoRealMaxActivation``.
"""

from __future__ import annotations

from typing import Final, Literal

FRACTIONS: Final = (0.05, 0.10, 0.15, 0.25, 0.40)
GENTLE: Final = (0.01, 0.02, 0.03, 0.05)
CAP: Final = 300.0


class NoRealMaxActivation(ValueError):
    """The feature reports no usable ``max_activation``."""


def _scale(max_activation: float | None) -> float:
    if (
        not isinstance(max_activation, int | float)
        or isinstance(max_activation, bool)
        or max_activation <= 0
    ):
        raise NoRealMaxActivation(str(max_activation))
    return float(max_activation)


def _cap(value: float) -> float:
    return max(-CAP, min(CAP, round(value, 2)))


def default_strengths(
    max_activation: float | None, direction: Literal["more", "less"] = "more"
) -> list[float]:
    scale = _scale(max_activation)
    sign = -1.0 if direction == "less" else 1.0
    return [_cap(sign * f * scale) for f in FRACTIONS]


def gentle_strengths(
    max_activation: float | None, direction: Literal["more", "less"] = "more"
) -> list[float]:
    """The next sweep when nothing was fluent (FTID §7)."""
    scale = _scale(max_activation)
    sign = -1.0 if direction == "less" else 1.0
    return [_cap(sign * f * scale) for f in GENTLE]
