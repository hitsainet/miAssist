"""FR-002.18/19: a suite planning a client whose registration is removed refuses to start."""

from __future__ import annotations

from pathlib import Path

from miassist_eval import classes, drivers
from tests.support import suites


def test_the_registry_holds_the_three_clients() -> None:
    assert set(drivers.REGISTRY) == {"scripted", "claude_code", "open_webui"}


async def test_a_suite_with_an_unregistered_client_refuses(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delitem(drivers.REGISTRY, "scripted")
    result = await suites.suite(tmp_path).run()
    assert result.refused is not None and result.refused.cls == classes.DRIVER_NOT_REGISTERED
    assert result.records == []


async def test_the_suite_reads_the_live_registry(tmp_path: Path) -> None:
    s = suites.suite(tmp_path)
    assert s.registry is drivers.REGISTRY
