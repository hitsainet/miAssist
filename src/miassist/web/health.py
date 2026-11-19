"""``GET /health`` (PADR ADR-003, ADR-016; Foundation task 9.2).

Coarse on purpose: it is unauthenticated and, once the public host opens, public. It names the
settings store's state and (from feature 001) each installed app's ``reachable``/``unreachable``,
never a URL or an internal reason. It never blocks longer than one second on the database ping.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any, Final

from starlette.requests import Request
from starlette.responses import JSONResponse

from miassist import __version__

PING_BUDGET_S: Final = 1.0


def make_health(
    ping: Callable[[], Awaitable[bool]],
    apps: Callable[[], dict[str, str]] = dict,
    missing_routes: Callable[[], dict[str, list[str]]] = dict,
) -> Callable[[Request], Awaitable[JSONResponse]]:
    """The ``/health`` endpoint over ``ping`` (the store's ``Database.ping``) and ``apps`` (each
    installed app's coarse state: ``reachable``, ``unreachable`` or ``unknown``; never a reason)."""

    async def health(request: Request) -> JSONResponse:
        try:
            ok = await asyncio.wait_for(ping(), timeout=PING_BUDGET_S)
        except Exception:
            ok = False
        body: dict[str, Any] = {
            "status": "ok",
            "service": "miassist",
            "version": __version__,
            "settings_store": "ok" if ok else "unavailable",
        }
        states = apps()
        if states:
            body["apps"] = states
        missing = missing_routes()
        if missing:
            body["missing_routes"] = missing
        return JSONResponse(body)

    return health
