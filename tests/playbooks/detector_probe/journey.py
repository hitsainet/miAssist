"""Drive the real ASGI app over the detector fakes, on a personal link (003 FTID §8).

``Journey`` keeps one app open; ``call`` returns the tool result (``structuredContent`` plus
``isError`` and the text); ``log()`` is every request any fake received, as
``(app, method, path, query, body, agent header)``, the request log FR-003.27 compares.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from miassist.adapters.base import HEADERS
from tests.playbooks.detector_probe.fakes import World, fakes_for
from tests.support.app_factory import client
from tests.support.http_mcp import call_tool
from tests.support.memory_store import MemoryStore
from tests.support.scenarios import URLS, inner_app, wait_probed

PERSON = "abcdefghijklmnopqrstuvwxyz"
ALL = ("miworkbench", "miserver", "midataworks")


class Journey:
    def __init__(
        self, test_client: Any, world: World, fakes: dict[str, Any], key: str | None
    ) -> None:
        self.client = test_client
        self.world = world
        self.fakes = fakes
        self.path = f"/p/{key}/mcp" if key else "/mcp"

    @property
    def runtime(self) -> Any:
        return inner_app(self.client).state.runtime

    def call(self, tool: str, args: dict[str, Any] | None = None) -> dict[str, Any]:
        result = call_tool(self.client, self.path, tool, args or {})
        return result

    def data(self, tool: str, args: dict[str, Any] | None = None) -> dict[str, Any]:
        result = self.call(tool, args)
        assert result["isError"] is False, result["content"][0]["text"]
        return result["structuredContent"]

    def log(self) -> list[tuple[str, str, str, str, str, str | None]]:
        out = []
        for app, fake in self.fakes.items():
            name = HEADERS[app][0].lower()
            for r in fake.requests:
                if r.path == "/api/health" or r.path.endswith("openapi.json"):
                    continue
                out.append(
                    (
                        app,
                        r.method,
                        r.path,
                        json.dumps(r.params, sort_keys=True),
                        json.dumps(r.body, sort_keys=True),
                        r.headers.get(name),
                    )
                )
        return out

    def writes(self, app: str | None = None) -> list[Any]:
        return [
            r
            for a, f in self.fakes.items()
            if app in (None, a)
            for r in f.requests
            if r.method != "GET" and not r.path.endswith("/forecast")
        ]


@contextmanager
def journey(
    installed: tuple[str, ...] = ALL,
    world: World | None = None,
    *,
    key: str | None = PERSON,
    level: str = "beginner",
    store: Any = None,
    **settings: Any,
) -> Iterator[Journey]:
    world = world if world is not None else World()
    fakes = fakes_for(world)
    with client(
        transports={a: f.transport() for a, f in fakes.items()},
        apps=",".join(installed),
        store=store if store is not None else MemoryStore(),
        **URLS,
        **settings,
    ) as test_client:
        wait_probed(test_client)
        j = Journey(test_client, world, fakes, key)
        if level == "expert" and key:
            j.data("miassist_set_guidance", {"level": "expert"})
        for fake in fakes.values():
            fake.requests.clear()
        yield j
