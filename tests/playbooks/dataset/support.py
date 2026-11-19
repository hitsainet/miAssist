"""An in-process session over the real server and a fake miDataworks (004 tests)."""

from __future__ import annotations

from typing import Any

from mcp import Client

from tests.playbooks.dataset.fake import Dataworks, fakes_with
from tests.support.fake_apps import FakeApp, Recorded
from tests.support.servers import make_server, mark_reachable


class Session:
    def __init__(
        self,
        dw: Dataworks | None = None,
        installed: tuple[str, ...] = ("midataworks",),
        store: Any = None,
    ) -> None:
        self.dw = dw or Dataworks()
        self.fakes = fakes_with(self.dw)
        self.mcp, self.deps = make_server(installed, self.fakes, store)

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

    async def status(self, subject: str) -> dict[str, Any]:
        result = await self.call("miassist_status", {"playbook": "dataset", "subject": subject})
        assert not result.is_error, result.content
        return result.structured_content["data"]["playbook"]  # type: ignore[no-any-return]

    @property
    def app(self) -> FakeApp:
        return self.fakes["midataworks"]

    def log(self, method: str | None = None, template: str | None = None) -> list[Recorded]:
        return self.app.calls(method, template)


def data(result: Any) -> dict[str, Any]:
    assert not result.is_error, result.content
    return result.structured_content["data"]  # type: ignore[no-any-return]
