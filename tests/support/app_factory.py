"""Build the real ASGI app for tests, with the store faked (no database needed)."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from starlette.testclient import TestClient

from miassist.app import create_app
from miassist.config import MiAssistSettings
from miassist.store.db import Database


class FakeDatabase(Database):
    """A ``Database`` whose ping answers ``healthy`` (or stalls ``stall_s`` seconds)."""

    def __init__(self, healthy: bool = True, stall_s: float = 0.0) -> None:
        self.healthy = healthy
        self.stall_s = stall_s
        self.pings = 0

    async def ping(self) -> bool:
        import asyncio

        self.pings += 1
        if self.stall_s:
            await asyncio.sleep(self.stall_s)
        return self.healthy

    async def dispose(self) -> None:
        return None


def settings(**overrides: Any) -> MiAssistSettings:
    base: dict[str, Any] = {"allowed_hosts": ["testserver", "localhost", "127.0.0.1"]}
    base.update(overrides)
    return MiAssistSettings(**base)


@contextmanager
def client(
    database: Database | None = None,
    *,
    store: Any = None,
    transports: Any = None,
    guidance: Any = None,
    definitions: Any = None,
    **overrides: Any,
) -> Iterator[TestClient]:
    from tests.support.memory_store import MemoryStore

    app = create_app(
        settings(**overrides),
        database=database or FakeDatabase(),
        store=store if store is not None else MemoryStore(),
        transports=transports,
        guidance=guidance,
        definitions=definitions,
    )
    with TestClient(app) as test_client:
        yield test_client


MCP_HEADERS = {"accept": "application/json, text/event-stream", "content-type": "application/json"}


def mcp_post(
    test_client: TestClient,
    path: str,
    method: str,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> Any:
    body = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}}
    return test_client.post(path, json=body, headers={**MCP_HEADERS, **(headers or {})})
