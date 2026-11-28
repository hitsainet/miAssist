"""The public host stays shut in code (CHAIN_PLAN A21, R1M-4; Foundation task 2.7).

A manifest cannot see a tunnel rule, and the public proxy rewrites the Host header to an internal
name (suite memory ``public-proxy-rewrites-host-header``), so a rule pointed at the LAN host would
reach miAssist with no repository change. Until ``PUBLIC_HOST_APPROVED`` is ``True`` the outermost
ASGI layer answers **404** ``{"error": "not_found"}`` to any request that carries ``cf-ray`` or
``cf-connecting-ip``, or whose ``Host``, ``X-Forwarded-Host``, ``X-Original-Host`` or
``Forwarded: host=`` names ``hitsai.net`` or ``*.hitsai.net`` (case and port ignored), on every
path, ``/health`` included.

Both constants are CODE, not settings, so no environment change can open the host or list
miWorkbench:

- ``PUBLIC_HOST_APPROVED`` - push 001-P (001 FTASKS 14.5) set it ``True``, in the same commit that
  edited ``tests/unit/test_public_host_constant.py`` (V-3). Before it, the tunnel rule
  ``mcp-assist.hitsai.net`` -> ingress-nginx with ``httpHostHeader: mcp-assist.hitsai.local`` was
  observed answering this guard's own 404 on ``/health`` and ``/mcp`` (2026-11-17, R2M-13). The
  request arrives with Host ``mcp-assist.hitsai.local`` plus ``cf-ray``/``cf-connecting-ip``; with
  the constant ``True`` the guard passes it and the MCP host check admits the listed Host
  (``tests/unit/test_public_host_real_path.py``).
- ``MIWORKBENCH_A0_LIVE`` - push 001-W (001 FTASKS 14.4) set it ``True``: miWorkbench 045-A0 is
  deployed (main ``463b29bea``, live 2026-11-17 01:31 UTC). It governs only whether
  ``miworkbench`` may appear in ``MIASSIST_APPS`` (read by the manifest test, V-11).
"""

from __future__ import annotations

import json
from typing import Final

from starlette.types import ASGIApp, Receive, Scope, Send

PUBLIC_HOST_APPROVED: Final = True
MIWORKBENCH_A0_LIVE: Final = True

PUBLIC_DOMAIN: Final = "hitsai.net"
_CLOUDFLARE_HEADERS: Final = frozenset({b"cf-ray", b"cf-connecting-ip"})
_HOST_HEADERS: Final = frozenset({b"host", b"x-forwarded-host", b"x-original-host"})
_NOT_FOUND: Final = json.dumps({"error": "not_found"}).encode()


def approved() -> bool:
    """The constant's value at call time (a module global, so a test can patch it)."""
    return bool(PUBLIC_HOST_APPROVED)


def _public_name(value: str) -> bool:
    for item in value.split(","):
        name = item.strip().lower()
        if name.startswith("[") and "]" in name:  # an IPv6 literal is never the public name
            continue
        name = name.rsplit(":", 1)[0] if name.count(":") == 1 else name
        name = name.rstrip(".")
        if name == PUBLIC_DOMAIN or name.endswith("." + PUBLIC_DOMAIN):
            return True
    return False


def _forwarded_hosts(value: str) -> list[str]:
    hosts = []
    for element in value.split(","):
        for pair in element.split(";"):
            name, _, raw = pair.strip().partition("=")
            if name.strip().lower() == "host":
                hosts.append(raw.strip().strip('"'))
    return hosts


def is_public_request(headers: list[tuple[bytes, bytes]]) -> bool:
    """True when the request came through the public proxy or names the public domain."""
    for raw_name, raw_value in headers:
        name = raw_name.lower()
        if name in _CLOUDFLARE_HEADERS:
            return True
        value = raw_value.decode("latin-1")
        if name in _HOST_HEADERS and _public_name(value):
            return True
        if name == b"forwarded" and any(_public_name(h) for h in _forwarded_hosts(value)):
            return True
    return False


class PublicHostGuard:
    """Pure ASGI; registered as the OUTERMOST layer by ``create_app``."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            scope["type"] in ("http", "websocket")
            and not approved()
            and is_public_request(list(scope.get("headers", [])))
        ):
            if scope["type"] == "websocket":
                await send({"type": "websocket.close", "code": 1008})
                return
            await send(
                {
                    "type": "http.response.start",
                    "status": 404,
                    "headers": [
                        (b"content-type", b"application/json"),
                        (b"content-length", str(len(_NOT_FOUND)).encode()),
                    ],
                }
            )
            await send({"type": "http.response.body", "body": _NOT_FOUND})
            return
        await self.app(scope, receive, send)
