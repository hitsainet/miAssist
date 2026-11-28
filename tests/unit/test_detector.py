"""Detection never blocks a call; one probe per interval; single flight (001 FR-2; FTASKS 3.3)."""

from __future__ import annotations

import asyncio
import time

import pytest

from miassist.adapters.base import AppClient, CallGuards, issue_public_check  # noqa: F401
from miassist.installed.detector import Detector
from tests.support.clients import client_for
from tests.support.fake_apps import FakeApp


async def test_never_blocks_a_call() -> None:
    async def slow() -> tuple[bool, str]:
        await asyncio.sleep(5)
        return True, "ok"

    detector = Detector({"miforge": slow})
    probe = asyncio.create_task(detector.probe("miforge"))
    await asyncio.sleep(0)
    start = time.monotonic()
    state = detector.snapshot("miforge")
    assert detector.unreachable_reason("miforge") is None
    assert time.monotonic() - start < 0.2
    assert state.state == "unknown"
    probe.cancel()


async def test_interval_and_single_flight() -> None:
    calls = {"miforge": 0, "miserver": 0}
    slept: list[float] = []
    gate = asyncio.Event()

    def probe_for(app: str):  # type: ignore[no-untyped-def]
        async def probe() -> tuple[bool, str]:
            calls[app] += 1
            await asyncio.sleep(0)
            return True, "ok"

        return probe

    async def fake_sleep(seconds: float) -> None:
        slept.append(seconds)
        if len(slept) >= 3:
            gate.set()
            await asyncio.Event().wait()

    detector = Detector({app: probe_for(app) for app in calls}, interval_s=60, sleep=fake_sleep)
    task = detector.start()
    await asyncio.wait_for(gate.wait(), 2)
    assert slept == [60, 60, 60]
    assert calls == {"miforge": 3, "miserver": 3}
    await detector.stop()
    assert task.done()

    together = Detector({"miforge": probe_for("miforge")})
    calls["miforge"] = 0
    await asyncio.gather(*(together.probe("miforge") for _ in range(10)))
    assert together.probe_counts["miforge"] == 1


@pytest.mark.parametrize(
    ("label", "fake_setup", "reason"),
    [
        ("ok", lambda f: f, "ok"),
        (
            "http-503",
            lambda f: f.on("GET", "/api/health", lambda r: __import__("httpx").Response(503)),
            "HTTP 503",
        ),
        (
            "not-json",
            lambda f: f.on(
                "GET", "/api/health", lambda r: __import__("httpx").Response(200, text="up")
            ),
            "not JSON",
        ),
        ("json-array", lambda f: f.on("GET", "/api/health", ["ok"]), "not JSON"),
    ],
)
async def test_states_and_reasons(label: str, fake_setup, reason: str) -> None:  # type: ignore[no-untyped-def]
    fake = fake_setup(FakeApp("midataworks"))
    client = client_for(fake)
    detector = Detector({"midataworks": lambda: client.probe_health(3)})
    state = await detector.probe("midataworks")
    assert state.reason == reason
    assert state.state == ("reachable" if reason == "ok" else "unreachable")
    assert Detector.public_reason(state) in ("reachable", "unreachable")


async def test_connection_refused_and_timeout() -> None:
    import httpx

    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    def slow(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    for handler, reason in ((refuse, "connection refused"), (slow, "timeout")):
        guards = client_for(FakeApp("miforge")).guards
        client = AppClient(
            "miforge", "http://miforge.test", guards, transport=httpx.MockTransport(handler)
        )
        assert await client.probe_health(3) == (False, reason)


async def test_mark_unreachable_is_immediate() -> None:
    async def ok() -> tuple[bool, str]:
        return True, "ok"

    detector = Detector({"miforge": ok})
    await detector.probe("miforge")
    detector.mark_unreachable("miforge", "connection refused")
    assert detector.unreachable_reason("miforge") == "connection refused"
