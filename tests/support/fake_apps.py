"""Fake apps behind ``httpx.MockTransport`` (001 FTID §8.2).

Each fake validates its app's agent header the way the app does (miWorkbench accepts only a bare
name and adds ``agent:`` itself; the others expect ``agent:<name>``), records every request, and
answers from handlers keyed by (method, path template). A route with no handler answers 404 with
the app's envelope. Nothing here imports miAssist's HTTP client: the transport is handed to
``AppClient``.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import unquote

import httpx

from miassist.adapters.base import HEADERS

Handler = Callable[["Recorded"], httpx.Response | dict[str, Any] | list[Any]]
_BARE_NAME = re.compile(r"^[a-z0-9][a-z0-9_-]{0,47}$")


@dataclass
class Recorded:
    method: str
    path: str
    template: str | None
    params: dict[str, str]
    headers: dict[str, str]
    body: Any
    path_params: dict[str, str] = field(default_factory=dict)


def _pattern(template: str) -> re.Pattern[str]:
    return re.compile(
        "^" + re.sub(r"\\\{([a-z_]+)\\\}", r"(?P<\1>[^/]+)", re.escape(template)) + "$"
    )


class FakeApp:
    """One app's fake: ``on(method, template, handler)``; ``requests`` records every request."""

    def __init__(self, app: str, *, healthy: bool = True) -> None:
        self.app = app
        self.requests: list[Recorded] = []
        self._handlers: list[tuple[str, str, re.Pattern[str], Handler]] = []
        self.on(
            "GET", "/api/health", lambda r: {"status": "ok"} if healthy else httpx.Response(503)
        )

    def on(
        self, method: str, template: str, handler: Handler | dict[str, Any] | list[Any]
    ) -> FakeApp:
        fn: Handler = handler if callable(handler) else (lambda _r, body=handler: body)
        self._handlers.insert(0, (method, template, _pattern(template), fn))
        return self

    def calls(self, method: str | None = None, template: str | None = None) -> list[Recorded]:
        return [
            r
            for r in self.requests
            if (method is None or r.method == method)
            and (template is None or r.template == template)
        ]

    def error(self, status: int, code: str, message: str = "refused") -> httpx.Response:
        if self.app == "miworkbench":
            return httpx.Response(status, json={"detail": {"code": code, "message": message}})
        return httpx.Response(status, json={"error": {"code": code, "message": message}})

    def _agent_ok(self, headers: httpx.Headers) -> bool:
        name, _ = HEADERS[self.app]
        value = headers.get(name)
        if value is None:
            return False
        if self.app == "miworkbench":
            return bool(_BARE_NAME.match(value))
        return value.startswith("agent:") and bool(_BARE_NAME.match(value.removeprefix("agent:")))

    def handle(self, request: httpx.Request) -> httpx.Response:
        body: Any = None
        if request.content:
            try:
                body = json.loads(request.content)
            except ValueError:
                body = request.content.decode(errors="replace")
        path = request.url.path
        recorded = Recorded(
            request.method, path, None, dict(request.url.params), dict(request.headers), body
        )
        self.requests.append(recorded)
        if not self._agent_ok(request.headers):
            return self.error(400, "agent_header_invalid", "bad agent header")
        # Match on the ENCODED path, so an id holding "/" stays one segment, then decode each
        # parameter as the app's router would.
        encoded = request.url.raw_path.split(b"?", 1)[0].decode("ascii")
        for method, template, pattern, handler in self._handlers:
            match = pattern.match(encoded)
            if method == request.method and match:
                recorded.template = template
                recorded.path_params = {k: unquote(v) for k, v in match.groupdict().items()}
                answer = handler(recorded)
                if isinstance(answer, httpx.Response):
                    return answer
                return httpx.Response(200, json=answer)
        return self.error(404, "not_found", "no such route")

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)


def all_fakes() -> dict[str, FakeApp]:
    return {app: FakeApp(app) for app in HEADERS}
