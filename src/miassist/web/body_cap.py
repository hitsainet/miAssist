"""The request-body cap (A24; 001 FR-30; FTID §3.14): pure ASGI, inside the public-host guard.

A ``content-length`` over the cap answers 413 at once; without one, the body is read up to the cap
first (413 as soon as it passes) and replayed to the app, so the app never sees an oversized body.
"""

from __future__ import annotations

import json
from typing import Final

from starlette.types import ASGIApp, Message, Receive, Scope, Send

_TOO_LARGE: Final = json.dumps({"error": "request_too_large"}).encode()


class BodyCap:
    def __init__(self, app: ASGIApp, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def _refuse(self, send: Send) -> None:
        await send(
            {
                "type": "http.response.start",
                "status": 413,
                "headers": [(b"content-type", b"application/json")],
            }
        )
        await send({"type": "http.response.body", "body": _TOO_LARGE})

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        for name, value in scope.get("headers", []):
            if name.lower() == b"content-length":
                try:
                    if int(value) > self.max_bytes:
                        await self._refuse(send)
                        return
                except ValueError:
                    await self._refuse(send)
                    return
        if not any(name.lower() == b"content-length" for name, _ in scope.get("headers", [])):
            # No declared length: read (at most the cap) first, then replay to the app.
            messages: list[Message] = []
            seen = 0
            while True:
                message = await receive()
                messages.append(message)
                if message["type"] != "http.request":
                    break
                seen += len(message.get("body", b""))
                if seen > self.max_bytes:
                    await self._refuse(send)
                    return
                if not message.get("more_body", False):
                    break
            replay = iter(messages)

            async def replayed() -> Message:
                try:
                    return next(replay)
                except StopIteration:
                    return await receive()

            await self.app(scope, replayed, send)
            return
        await self.app(scope, receive, send)
