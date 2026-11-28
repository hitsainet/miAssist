"""One monotonic clock per harness process, with a wall-clock anchor (TD-1; FTID §11)."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")


def utc_now() -> datetime:
    return datetime.now(UTC)


def to_et(when: datetime) -> str:
    """A UTC time rendered in US Eastern (reports and readings are in ET)."""
    return when.astimezone(ET).strftime("%Y-%m-%d %H:%M %Z")


@dataclass
class Clock:
    """``mono()`` in seconds since the anchor; ``wall()`` the anchor plus that offset."""

    source: Callable[[], int] = time.monotonic_ns
    anchor_wall: datetime = field(default_factory=utc_now)
    anchor_mono_ns: int = 0

    def __post_init__(self) -> None:
        self.anchor_mono_ns = self.source()

    def mono(self) -> float:
        return (self.source() - self.anchor_mono_ns) / 1e9

    def stamp(self) -> dict[str, object]:
        return {"t_mono": round(self.mono(), 6), "anchor_utc": self.anchor_wall.isoformat()}
