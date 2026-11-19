"""Degrade by name when the settings store is down (PADR ADR-004; 001 FR-7; FTDD §4.2).

A connection error or a 1 s timeout marks the store unavailable for 30 s. While it is: reads answer
the defaults (no level remembered, no progress), and writes raise ``StoreUnavailable``, which tools
map to ``unavailable: "settings_store"``. No tool fails because the store is down.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from typing import Any, Protocol, TypeVar

T = TypeVar("T")
TIMEOUT_S = 1.0
COOL_OFF_S = 30.0


class StoreUnavailable(Exception):
    """The settings store cannot be written now."""


class Store(Protocol):
    async def level(self, key_hash: str) -> str | None: ...

    async def set_level(self, key_hash: str, level: str) -> None: ...

    async def progress(
        self, key_hash: str, playbook_id: str, subject: str = ""
    ) -> dict[str, Any] | None: ...

    async def save_progress(
        self, key_hash: str, playbook_id: str, subject: str, version: int, state: dict[str, Any]
    ) -> None: ...

    async def forget(self, key_hash: str) -> None: ...

    async def sweep(self, now: Any, retention_days: int) -> int: ...


class DegradingStore:
    """``inner`` with the degrade-by-name rule applied to every call."""

    def __init__(self, inner: Store, clock: Callable[[], float] = time.monotonic) -> None:
        self.inner = inner
        self._clock = clock
        self._down_until = 0.0
        #: Calls that reached the inner store's write methods (read by the no-write test).
        self.writes = 0

    @property
    def available(self) -> bool:
        return self._clock() >= self._down_until

    async def _guard(self, call: Callable[[], Awaitable[T]], default: T, *, write: bool) -> T:
        if not self.available:
            if write:
                raise StoreUnavailable("settings_store")
            return default
        try:
            return await asyncio.wait_for(call(), TIMEOUT_S)
        except Exception as exc:
            self._down_until = self._clock() + COOL_OFF_S
            if write:
                raise StoreUnavailable("settings_store") from exc
            return default

    async def level(self, key_hash: str) -> str | None:
        return await self._guard(lambda: self.inner.level(key_hash), None, write=False)

    async def set_level(self, key_hash: str, level: str) -> None:
        self.writes += 1
        await self._guard(lambda: self.inner.set_level(key_hash, level), None, write=True)

    async def progress(
        self, key_hash: str, playbook_id: str, subject: str = ""
    ) -> dict[str, Any] | None:
        return await self._guard(
            lambda: self.inner.progress(key_hash, playbook_id, subject), None, write=False
        )

    async def save_progress(
        self, key_hash: str, playbook_id: str, subject: str, version: int, state: dict[str, Any]
    ) -> None:
        self.writes += 1
        await self._guard(
            lambda: self.inner.save_progress(key_hash, playbook_id, subject, version, state),
            None,
            write=True,
        )

    async def forget(self, key_hash: str) -> None:
        self.writes += 1
        await self._guard(lambda: self.inner.forget(key_hash), None, write=True)

    async def sweep(self, now: Any, retention_days: int) -> int:
        return await self._guard(lambda: self.inner.sweep(now, retention_days), 0, write=True)
