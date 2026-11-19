"""Fast task polls for the steering playbook's tests."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from miassist.playbooks.steering import actions
from miassist.vendored import requests
from tests.support import shapes

GPU_SCHEMAS = Path(__file__).with_name("gpu_request_schemas.json")


@pytest.fixture(autouse=True)
def quick_polls(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(actions, "POLL_WINDOW_S", 0.05)
    monkeypatch.setattr(actions, "POLL_INTERVAL_S", 0.01)


@pytest.fixture(autouse=True)
def gpu_request_schemas(monkeypatch: pytest.MonkeyPatch) -> None:
    """The test registry's GPU routes need their request schemas in Core's lookup (production lists
    only registered file-first routes; the GPU routes register after 045's rows land)."""
    table: dict[str, Any] = {**requests._table(), **json.loads(GPU_SCHEMAS.read_text())["routes"]}
    monkeypatch.setattr(requests, "_table", lambda: table)


@pytest.fixture(autouse=True)
def answers_are_the_apps() -> Iterator[None]:
    """Every answer the fake miWorkbench and miServer give is one they can give (R1 review fixes
    OR1-pb-2 to OR1-pb-5, 2026-11-16; ``tests/support/shapes.py``)."""
    shapes.collected()
    yield
    found = shapes.collected()
    assert not found, "fake answers the apps never give:\n" + "\n".join(found[:20])
