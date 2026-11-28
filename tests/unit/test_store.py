"""Degrade by name; the sweep is started by the lifespan (001 FTASKS 6.3, 6.5)."""

from __future__ import annotations

import asyncio
from datetime import datetime

import pytest
from starlette.testclient import TestClient

from miassist.app import create_app
from miassist.store.degrading import DegradingStore, StoreUnavailable
from miassist.store.sweep import EASTERN, Sweeper, seconds_until_next
from tests.support.app_factory import FakeDatabase, settings
from tests.support.memory_store import MemoryStore


async def test_degrade_reads_default() -> None:
    store = DegradingStore(MemoryStore(down=True))
    assert await store.level("h") is None
    assert await store.progress("h", "p") is None
    assert not store.available


async def test_degrade_write_unavailable() -> None:
    inner = MemoryStore(down=True)
    store = DegradingStore(inner)
    with pytest.raises(StoreUnavailable):
        await store.set_level("h", "expert")
    inner.down = False
    with pytest.raises(StoreUnavailable):  # still inside the 30 s cool-off
        await store.set_level("h", "expert")


async def test_slow_store_degrades_within_a_second() -> None:
    class Slow(MemoryStore):
        async def level(self, key_hash: str) -> str | None:
            await asyncio.sleep(5)
            return "expert"

    store = DegradingStore(Slow())
    start = asyncio.get_running_loop().time()
    assert await store.level("h") is None
    assert asyncio.get_running_loop().time() - start < 1.5


def test_next_sweep_is_five_eastern() -> None:
    before = datetime(2026, 11, 16, 4, 0, tzinfo=EASTERN)
    assert seconds_until_next(before) == 3600
    after = datetime(2026, 11, 16, 6, 0, tzinfo=EASTERN)
    assert seconds_until_next(after) == 23 * 3600


async def test_sweep() -> None:
    calls: list[tuple[datetime, int]] = []

    class Recording(MemoryStore):
        async def sweep(self, now: datetime, retention_days: int) -> int:
            calls.append((now, retention_days))
            return 2

    slept: list[float] = []
    done = asyncio.Event()

    async def fake_sleep(seconds: float) -> None:
        slept.append(seconds)
        if len(slept) > 1:
            done.set()
            await asyncio.Event().wait()

    now = datetime(2026, 11, 16, 4, 59, tzinfo=EASTERN)
    sweeper = Sweeper(Recording(), 180, now=lambda: now, sleep=fake_sleep)
    sweeper.start()
    await asyncio.wait_for(done.wait(), 2)
    await sweeper.stop()
    assert slept[0] == 60 and calls == [(now, 180)]


def test_sweep_started_by_lifespan() -> None:
    app = create_app(settings(), database=FakeDatabase(), store=MemoryStore())
    inner = app
    while not hasattr(inner, "state"):
        inner = inner.app  # type: ignore[attr-defined]
    runtime = inner.state.runtime
    assert not runtime.sweeper.running
    with TestClient(app):
        assert runtime.sweeper.running
    assert not runtime.sweeper.running
