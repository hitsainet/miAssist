"""The per-person key in the URL path (001 FR-6; spike S-1's fallback, recorded in the controls).

``KeyShim`` is pure ASGI. A request to ``/p/<key>/mcp`` with a well-formed key is forwarded as
``/mcp`` with the key in ``scope["state"]["miassist_key"]``; a malformed key answers 404 naming
``/p/new`` and the MCP app is never invoked. Every other path passes untouched. The key selects
remembered settings only: no code path grants or refuses anything by it.
"""

from __future__ import annotations

import json
import re
from typing import Final

from starlette.types import ASGIApp, Receive, Scope, Send

KEY_PATTERN: Final = re.compile(r"^[a-z2-7]{26}$")
_KEYED_MCP: Final = re.compile(r"^/p/([^/]+)/mcp/?$")
STATE_KEY: Final = "miassist_key"
_NOT_FOUND: Final = json.dumps(
    {"error": "not_found", "detail": "unknown link; open /p/new for a personal link"}
).encode()


class KeyShim:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            match = _KEYED_MCP.match(scope.get("path", ""))
            if match:
                key = match.group(1)
                if not KEY_PATTERN.fullmatch(key):
                    await send(
                        {
                            "type": "http.response.start",
                            "status": 404,
                            "headers": [(b"content-type", b"application/json")],
                        }
                    )
                    await send({"type": "http.response.body", "body": _NOT_FOUND})
                    return
                state = dict(scope.get("state") or {})
                state[STATE_KEY] = key
                scope = {**scope, "path": "/mcp", "raw_path": b"/mcp", "state": state}
        await self.app(scope, receive, send)


def key_from_scope(scope: object) -> str | None:
    """The key a request carried, or ``None`` (``/mcp``)."""
    if not isinstance(scope, dict):
        return None
    state = scope.get("state") or {}
    key = state.get(STATE_KEY) if isinstance(state, dict) else None
    return key if isinstance(key, str) and KEY_PATTERN.fullmatch(key) else None
