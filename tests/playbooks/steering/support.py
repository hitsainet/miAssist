"""An in-process session for the steering tests; ``gpu=True`` registers the two GPU routes on a
TEST registry (production registers them only from 045's vendored rows; OVN-miassist-pb045-13).

Integration (OVN-miassist-int-18), 2026-11-16: production now registers both (the vendored vectors
carry rows 31 and 32), so ``gpu=True`` is production's set and ``gpu=False`` is a registry WITHOUT
them, which keeps the not-ready refusal pinned."""

from __future__ import annotations

import hashlib
from typing import Any

from mcp import Client

from miassist.adapters.routes import ROUTES, RouteRegistry
from miassist.adapters.steering import GPU_ROUTES
from miassist.guidance.loader import Guidance
from miassist.runtime import build_runtime
from miassist.server.build import build_server
from miassist.server.specs import Deps
from miassist.tools import all_specs
from tests.playbooks.steering.fake import Steering, fakes_with
from tests.support.app_factory import settings
from tests.support.fake_apps import FakeApp, Recorded
from tests.support.memory_store import MemoryStore
from tests.support.servers import mark_reachable

APPS = ("miworkbench", "miserver", "midataworks", "miforge")
#: The personal key of the ``keyed`` fixture (conftest) and its hash, as the store holds it.
KEY = "acceptanceacceptanceaccept"
KEY_HASH = hashlib.sha256(KEY.encode("ascii")).hexdigest()


def gpu_registry() -> RouteRegistry:
    held = {r.id for r in ROUTES}
    return RouteRegistry((*ROUTES, *(r for r in GPU_ROUTES if r.id not in held)))


def registry_without_gpu() -> RouteRegistry:
    gpu = {r.id for r in GPU_ROUTES}
    return RouteRegistry(tuple(r for r in ROUTES if r.id not in gpu))


class Session:
    def __init__(
        self,
        s: Steering | None = None,
        installed: tuple[str, ...] = ("miworkbench", "miserver"),
        *,
        gpu: bool = True,
        store: Any = None,
    ) -> None:
        self.s = s or Steering()
        self.fakes = fakes_with(self.s)
        urls = {f"{a}_url": f"http://{a}.test" for a in APPS}
        runtime = build_runtime(
            settings(apps=",".join(installed), **urls),
            transports={a: f.transport() for a, f in self.fakes.items()},
            registry=gpu_registry() if gpu else registry_without_gpu(),
            store=store if store is not None else MemoryStore(),
        )
        self.deps = Deps(runtime=runtime, guidance=Guidance())
        self.mcp = build_server(self.deps, all_specs())

    async def __aenter__(self) -> Session:
        await mark_reachable(self.deps)
        for fake in self.fakes.values():
            fake.requests.clear()
        self._client = Client(self.mcp)
        await self._client.__aenter__()
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self._client.__aexit__(*exc)

    async def call(self, tool: str, args: dict[str, Any]) -> Any:
        return await self._client.call_tool(tool, args)

    @property
    def wb(self) -> FakeApp:
        return self.fakes["miworkbench"]

    @property
    def sv(self) -> FakeApp:
        return self.fakes["miserver"]

    def log(
        self, app: str, method: str | None = None, template: str | None = None
    ) -> list[Recorded]:
        return self.fakes[app].calls(method, template)


def data(result: Any) -> dict[str, Any]:
    assert not result.is_error, result.content
    return result.structured_content["data"]  # type: ignore[no-any-return]
