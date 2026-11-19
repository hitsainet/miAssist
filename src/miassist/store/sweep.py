"""The retention sweep (001 FR-20): daily at 05:00 US Eastern, started by the app's lifespan.

Deletes the rows of keys not used for ``retention_days`` (180 by default). Idempotent, so several
replicas sweeping at once is harmless. A failed sweep is logged and retried the next day.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

EASTERN = ZoneInfo("America/New_York")
SWEEP_HOUR = 5
_log = logging.getLogger("miassist.sweep")


def seconds_until_next(now: datetime) -> float:
    """Seconds from ``now`` (aware) to the next 05:00 US Eastern."""
    local = now.astimezone(EASTERN)
    target = local.replace(hour=SWEEP_HOUR, minute=0, second=0, microsecond=0)
    if target <= local:
        target += timedelta(days=1)
    return (target - local).total_seconds()


class Sweeper:
    def __init__(
        self,
        store: Any,
        retention_days: int,
        *,
        now: Callable[[], datetime] = lambda: datetime.now(EASTERN),
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self.store = store
        self.retention_days = retention_days
        self._now = now
        self._sleep = sleep
        self._task: asyncio.Task[None] | None = None
        self.runs = 0

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    async def run_once(self) -> int:
        self.runs += 1
        try:
            removed = int(await self.store.sweep(self._now(), self.retention_days))
        except Exception:
            _log.warning("the retention sweep failed; it runs again tomorrow")
            return 0
        _log.info("retention sweep done", extra={"removed": removed})
        return removed

    async def _loop(self) -> None:
        while True:
            await self._sleep(seconds_until_next(self._now()))
            await self.run_once()

    def start(self) -> None:
        if not self.running:
            self._task = asyncio.get_running_loop().create_task(self._loop())

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
