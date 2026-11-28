"""The MCP tap (FR-002.17; FTID §3.4): a reverse proxy in front of the server under test that never
changes a byte in either direction and logs each JSON-RPC ``tools/call``, ``tools/list``,
``initialize`` and ``server/discover`` with its answer.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

import httpx
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Route as StarletteRoute

from miassist_eval.canonical import sha256
from miassist_eval.clock import Clock

LOGGED = frozenset({"tools/call", "tools/list", "initialize", "server/discover"})
HOP = frozenset({"host", "content-length", "transfer-encoding", "connection", "keep-alive"})


def _messages(body: bytes) -> list[Mapping[str, Any]]:
    try:
        parsed = json.loads(body) if body else None
    except ValueError:
        return []
    if isinstance(parsed, Mapping):
        return [parsed]
    if isinstance(parsed, list):
        return [m for m in parsed if isinstance(m, Mapping)]
    return []


def answers(content_type: str, body: bytes) -> list[Mapping[str, Any]]:
    """JSON-RPC answers from a JSON body or from an event stream's ``data:`` lines."""
    if "text/event-stream" in content_type:
        out: list[Mapping[str, Any]] = []
        for event in body.decode("utf-8", "replace").split("\n\n"):
            data = "\n".join(ln[5:].lstrip() for ln in event.splitlines() if ln.startswith("data:"))
            out += _messages(data.encode())
        return out
    return _messages(body)


@dataclass
class Tap:
    upstream: str
    clock: Clock = field(default_factory=Clock)
    log: list[dict[str, Any]] = field(default_factory=list)
    skip_methods: frozenset[str] = frozenset()

    def _record(self, t0: float, request_body: bytes, content_type: str, answer: bytes) -> None:
        replies = {str(a.get("id")): a for a in answers(content_type, answer) if "id" in a}
        for msg in _messages(request_body):
            method = str(msg.get("method", ""))
            if method not in LOGGED or method in self.skip_methods:
                continue
            params = msg.get("params") or {}
            reply = replies.get(str(msg.get("id")), {})
            result = reply.get("result") if isinstance(reply, Mapping) else None
            self.log.append(
                {
                    "t_mono": round(t0, 6),
                    "t_answer": round(self.clock.mono(), 6),
                    "rpc_id": msg.get("id"),
                    "method": method,
                    "tool": params.get("name") if method == "tools/call" else None,
                    "args_sha256": (
                        sha256(params.get("arguments")) if method == "tools/call" else None
                    ),
                    "is_error": bool(isinstance(result, Mapping) and result.get("isError"))
                    or "error" in reply,
                    "answer_bytes": len(answer),
                    "answer_chars": len(answer.decode("utf-8", "replace")),
                    "latency_ms": round((self.clock.mono() - t0) * 1000, 3),
                    "result": result if method == "tools/list" else None,
                }
            )

    def app(self) -> Starlette:
        client = httpx.AsyncClient(base_url=self.upstream, timeout=None)

        async def endpoint(request: Request) -> Response:
            t0 = self.clock.mono()
            body = await request.body()
            headers = {k: v for k, v in request.headers.items() if k.lower() not in HOP}
            upstream = await client.request(
                request.method,
                request.url.path,
                params=request.query_params,
                headers=headers,
                content=body,
            )
            answer = upstream.content
            ctype = upstream.headers.get("content-type", "")
            self._record(t0, body, ctype, answer)
            out_headers = {
                k: v
                for k, v in upstream.headers.items()
                if k.lower() not in HOP and k.lower() != "content-encoding"
            }
            return Response(content=answer, status_code=upstream.status_code, headers=out_headers)

        methods = ["GET", "POST", "PUT", "PATCH", "DELETE"]
        return Starlette(routes=[StarletteRoute("/{path:path}", endpoint, methods=methods)])

    def count(self, method: str = "tools/call") -> int:
        return sum(1 for line in self.log if line["method"] == method)
