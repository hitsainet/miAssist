"""Raw JSON-RPC over the real ASGI app's HTTP transport (stateless, JSON responses)."""

from __future__ import annotations

from typing import Any

from starlette.testclient import TestClient

HEADERS = {"accept": "application/json, text/event-stream", "content-type": "application/json"}


def rpc(
    client: TestClient,
    path: str,
    method: str,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    body = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}}
    response = client.post(path, json=body, headers={**HEADERS, **(headers or {})})
    assert response.status_code == 200, (response.status_code, response.text)
    answer: dict[str, Any] = response.json()
    assert "result" in answer, answer
    return answer["result"]  # type: ignore[no-any-return]


def call_tool(
    client: TestClient,
    path: str,
    name: str,
    args: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    return rpc(client, path, "tools/call", {"name": name, "arguments": args or {}}, headers)
