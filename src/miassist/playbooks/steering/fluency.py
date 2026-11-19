"""The fluency verdict (005 FTDD §6 ``fluency.py``; FTID I4; FPRD FR-005.13). Pure.

``ttr``: distinct lower-cased word tokens over all of them (``[\\w']+``); fewer than 5 tokens counts
as collapsed (an almost empty reply). A reply collapses when its TTR is below 0.4, the guide's rule
("text with fewer than 4 distinct words in 10 is treated as fallen apart"). The usable strength is
the largest |strength| before the first collapse, in sweep order; none when the first collapses.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Final

COLLAPSE_BELOW: Final = 0.4
MIN_TOKENS: Final = 5
EXCERPT: Final = 300
_WORD: Final = re.compile(r"[\w']+")


def ttr(text: str | None) -> float:
    tokens = _WORD.findall((text or "").lower())
    if not tokens:
        return 0.0
    return round(len(set(tokens)) / len(tokens), 3)


def collapsed(text: str | None) -> bool:
    return len(_WORD.findall((text or "").lower())) < MIN_TOKENS or ttr(text) < COLLAPSE_BELOW


def excerpt(text: str | None, limit: int = EXCERPT) -> str:
    flat = " ".join((text or "").split())
    return flat if len(flat) <= limit else flat[: limit - 1] + "…"


@dataclass(frozen=True)
class Fluency:
    usable: float | None
    first_collapse: float | None
    rows: list[dict[str, Any]] = field(default_factory=list)
    unsteered: dict[str, Any] | None = None


def verdict(unsteered: str | None, results: Sequence[tuple[float, str | None]]) -> Fluency:
    rows = []
    usable: float | None = None
    first: float | None = None
    for strength, text in results:
        down = collapsed(text)
        rows.append(
            {"strength": strength, "ttr": ttr(text), "collapsed": down, "excerpt": excerpt(text)}
        )
        if down and first is None:
            first = strength
        if first is None and (usable is None or abs(strength) > abs(usable)):
            usable = strength
    base = None
    if unsteered is not None:
        base = {
            "ttr": ttr(unsteered),
            "collapsed": collapsed(unsteered),
            "excerpt": excerpt(unsteered),
        }
    return Fluency(usable, first, rows, base)
