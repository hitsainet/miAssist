"""The detector is started by the app's lifespan (001 FR-2, AC-2.3; FTASKS 3.2)."""

from __future__ import annotations

import time

from starlette.testclient import TestClient

from miassist.app import create_app
from tests.support.app_factory import FakeDatabase, settings
from tests.support.fake_apps import all_fakes

URLS = {
    f"{app}_url": f"http://{app}.test"
    for app in ("miworkbench", "miserver", "midataworks", "miforge")
}


def test_detector_started() -> None:
    fakes = all_fakes()
    app = create_app(
        settings(apps="miworkbench,miserver,midataworks,miforge", **URLS),
        database=FakeDatabase(),
        transports={name: fake.transport() for name, fake in fakes.items()},
    )
    with TestClient(app):
        deadline = time.monotonic() + 1.0
        while time.monotonic() < deadline and not all(
            f.calls("GET", "/api/health") for f in fakes.values()
        ):
            time.sleep(0.02)
        for name, fake in fakes.items():
            assert len(fake.calls("GET", "/api/health")) == 1, name
