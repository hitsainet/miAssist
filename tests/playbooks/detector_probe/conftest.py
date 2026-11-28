"""Every answer a detector-probe fake gives in a test is the app's real shape (R1 review fix,
OR1-pb-6 to OR1-pb-9, 2026-11-16): a test whose fakes invented or dropped a field fails here."""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from tests.playbooks.detector_probe import fakes


@pytest.fixture(autouse=True)
def fakes_answer_in_the_apps_shapes() -> Iterator[None]:
    fakes.CREATED.clear()
    yield
    found = [v for fake in fakes.CREATED for v in fake.shape_violations]
    fakes.CREATED.clear()
    assert not found, "a fake answered in a shape the app never sends:\n" + "\n".join(found[:20])
