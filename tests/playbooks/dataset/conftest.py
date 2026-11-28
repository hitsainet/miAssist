"""Fast job polls for the dataset playbook's tests (the 10-second window is production's)."""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from miassist.playbooks.dataset import actions
from tests.support import shapes


@pytest.fixture(autouse=True)
def quick_polls(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(actions, "POLL_WINDOW_S", 0.05)
    monkeypatch.setattr(actions, "POLL_INTERVAL_S", 0.01)


@pytest.fixture(autouse=True)
def answers_are_the_apps() -> Iterator[None]:
    """Every answer the fake miDataworks gives is one miDataworks can give (R1 review fix
    OR1-pb-1, 2026-11-16; ``tests/support/shapes.py``)."""
    shapes.collected()
    yield
    found = shapes.collected()
    assert not found, "fake answers the app never gives:\n" + "\n".join(found[:20])
