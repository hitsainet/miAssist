# Origin: miForge (Onegaishimas/miForge) backend/src/mcp_server/health_gate.py @ e4251e4
# Mode: adapt (docs/REUSE.md). Kept: single flight, a never-blocking snapshot, public_reason.
# Changed: N apps, a fixed-interval loop started by the app's lifespan (001 FR-2), probes through
# each app's own client (httpx stays in adapters/base.py), mark_unreachable from a failed call.
"""Detection of the installed apps (001 FR-2; PADR ADR-007).

At start and every ``interval_s`` (60 s), each installed app's ``GET /api/health`` (3 s timeout)
sets its state: ``reachable`` (HTTP 200 with a JSON object) or ``unreachable`` with a plain reason
(``timeout``, ``connection refused``, ``HTTP 503``, ``not JSON``). Tool calls read the cached
snapshot and NEVER await a probe. A connection failure during a tool call marks the app
unreachable at once.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Literal

Probe = Callable[[], Awaitable[tuple[bool, str]]]
Sleep = Callable[[float], Awaitable[None]]
_log = logging.getLogger("miassist.detector")


@dataclass(frozen=True)
class AppState:
    state: Literal["unknown", "reachable", "unreachable"]
    reason: str
    checked_at: float | None


class Detector:
    """The snapshot of every installed app's reachability."""

    def __init__(
        self,
        probes: Mapping[str, Probe],
        *,
        interval_s: float = 60.0,
        clock: Callable[[], float] = time.monotonic,
        sleep: Sleep = asyncio.sleep,
    ) -> None:
        self._probes = dict(probes)
        self._interval = interval_s
        self._clock = clock
        self._sleep = sleep
        self._states = {app: AppState("unknown", "not probed yet", None) for app in self._probes}
        self._inflight: dict[str, asyncio.Task[AppState]] = {}
        self._loop_task: asyncio.Task[None] | None = None
        #: Probes made per app, read by the single-flight and interval tests.
        self.probe_counts = dict.fromkeys(self._probes, 0)

    @property
    def apps(self) -> list[str]:
        return list(self._probes)

    def snapshot(self, app: str) -> AppState:
        """The last known state; never probes, never waits."""
        return self._states[app]

    def unreachable_reason(self, app: str) -> str | None:
        state = self._states.get(app)
        if state is None:
            return "not installed"
        return state.reason if state.state == "unreachable" else None

    def mark_unreachable(self, app: str, reason: str) -> None:
        if app in self._states:
            self._states[app] = AppState("unreachable", reason, self._clock())

    async def _probe(self, app: str) -> AppState:
        self.probe_counts[app] += 1
        try:
            ok, reason = await self._probes[app]()
        except Exception:
            ok, reason = False, "probe failed"
        state = AppState("reachable" if ok else "unreachable", reason, self._clock())
        self._states[app] = state
        return state

    async def probe(self, app: str) -> AppState:
        """Probe one app; concurrent callers share one probe (single flight)."""
        task = self._inflight.get(app)
        if task is None or task.done():
            task = asyncio.get_running_loop().create_task(self._probe(app))
            self._inflight[app] = task
        return await asyncio.shield(task)

    async def probe_all(self) -> None:
        await asyncio.gather(*(self.probe(app) for app in self._probes))

    async def run(self) -> None:
        while True:
            await self.probe_all()
            await self._sleep(self._interval)

    def start(self) -> asyncio.Task[None]:
        """Start the loop (the app's lifespan calls this; 001 AC-2.3)."""
        if self._loop_task is None or self._loop_task.done():
            self._loop_task = asyncio.get_running_loop().create_task(self.run())
        return self._loop_task

    async def stop(self) -> None:
        task, self._loop_task = self._loop_task, None
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        for inflight in self._inflight.values():
            inflight.cancel()

    @staticmethod
    def public_reason(state: AppState) -> str:
        """A coarse word safe for the unauthenticated ``/health``: never a URL or an internal reason."""
        return state.state
