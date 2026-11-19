"""A stub MCP server under test (FTDD §10): three tools that call the apps' REST APIs at the
listener URLs it is given, with each app's agent header, as a server under test would."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import httpx
from mcp.server.mcpserver import MCPServer

from miassist_eval.servers import serve
from tests.support.harness import HEADERS


def build(
    app_urls: Mapping[str, str],
    header_override: Mapping[str, Mapping[str, str]] | None = None,
    extra_tool: bool = False,
) -> MCPServer:
    mcp = MCPServer("stub-under-test")
    headers = {**HEADERS, **(header_override or {})}

    async def call(app: str, method: str, path: str, body: Any = None) -> Any:
        async with httpx.AsyncClient(base_url=app_urls[app], timeout=10) as client:
            resp = await client.request(
                method, path, headers=dict(headers[app]), json=body if body is not None else None
            )
            return {"status": resp.status_code, "body": resp.json()}

    @mcp.tool()
    async def list_sets() -> dict:
        """List the dataset collection."""
        return await call("midataworks", "GET", "/api/v1/datasets")

    @mcp.tool()
    async def build_set(dataset_id: str) -> dict:
        """Build a version of a dataset."""
        return await call("midataworks", "POST", "/api/v1/versions", {"dataset_id": dataset_id})

    @mcp.tool()
    async def read_version(version_id: str) -> dict:
        """Read one version."""
        return await call("midataworks", "GET", f"/api/v1/versions/{version_id}")

    @mcp.tool()
    async def call_app(app: str, method: str, path: str, body: dict | None = None) -> dict:
        """Send one request to one app."""
        return await call(app, method, path, body)

    if extra_tool:

        @mcp.tool()
        async def miassist_guide() -> str:
            """A tool whose name a hinted goal might carry."""
            return "guide"

    return mcp


def factory(**kw: Any):
    async def start(app_urls: Mapping[str, str]):
        mcp = build(app_urls, **kw)
        listener = await serve(mcp.streamable_http_app(json_response=True, stateless_http=True))
        return f"{listener.url}/mcp", listener.stop

    return start
