"""The runtime route check (001 FR-15, AC-15.5; FTASKS 3.4).

The committed snapshots pin what miAssist was BUILT against; this checks what the RUNNING app
publishes. The first time an installed app answers its health probe, miAssist reads the app's own
OpenAPI description once and compares it with the routes registered for that app. A registered
route the running app does not publish is ``missing``: ``AppClient.call`` answers it
``app_route_missing`` instead of sending, and ``/health`` lists it. The tool list never changes
(FR-3): a tool whose route is missing still exists and says why it cannot help.

The check runs inside the detector's probe (never in a tool call's path). An unreadable
description leaves the app unchecked (nothing is marked missing) and is tried again at the next
probe.
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable, Iterable
from typing import Any, Final, Protocol

#: Where each app publishes its OpenAPI description (FTASKS 3.4).
OPENAPI_PATHS: Final[dict[str, str]] = {
    "miworkbench": "/api/openapi.json",
    "miserver": "/openapi.json",
    "midataworks": "/api/v1/openapi.json",
    "miforge": "/api/openapi.json",
}
_PARAM: Final = re.compile(r"\{[^}]*\}")


class _Route(Protocol):
    @property
    def id(self) -> str: ...

    @property
    def method(self) -> str: ...

    @property
    def path(self) -> str: ...


class _Fetcher(Protocol):
    async def get_json(self, path: str, timeout_s: float) -> Any: ...


def _shape(path: str) -> str:
    """A path with every parameter name erased: ``/a/{run_id}`` and ``/a/{id}`` are one route."""
    return _PARAM.sub("{}", path.rstrip("/") or "/")


def published(document: Any) -> frozenset[tuple[str, str]] | None:
    """``(METHOD, path shape)`` for every operation in an OpenAPI document; ``None`` if it is not
    one."""
    if not isinstance(document, dict) or not isinstance(document.get("paths"), dict):
        return None
    out: set[tuple[str, str]] = set()
    for path, item in document["paths"].items():
        if not isinstance(item, dict):
            continue
        for method in item:
            if method.lower() in {"get", "put", "post", "delete", "patch", "head", "options"}:
                out.add((method.upper(), _shape(str(path))))
    return frozenset(out)


def missing_from(routes: Iterable[_Route], document: Any) -> frozenset[str] | None:
    """The ids of ``routes`` the document does not publish; ``None`` if the document is unusable."""
    ops = published(document)
    if ops is None:
        return None
    return frozenset(r.id for r in routes if (r.method.upper(), _shape(r.path)) not in ops)


class OpenApiCheck:
    """Each installed app's missing routes, read once per process from the running app."""

    def __init__(
        self,
        routes_for: Callable[[str], Iterable[_Route]],
        *,
        timeout_s: float = 3.0,
    ) -> None:
        self._routes_for = routes_for
        self._timeout = timeout_s
        self._missing: dict[str, frozenset[str]] = {}
        #: Description reads per app (the "read once" test).
        self.reads: dict[str, int] = {}

    def checked(self, app: str) -> bool:
        return app in self._missing

    def missing(self, app: str) -> frozenset[str]:
        """The registered route ids the running ``app`` lacks (empty until checked)."""
        return self._missing.get(app, frozenset())

    def all_missing(self) -> dict[str, list[str]]:
        return {app: sorted(ids) for app, ids in sorted(self._missing.items()) if ids}

    async def run(self, app: str, fetcher: _Fetcher) -> None:
        if self.checked(app):
            return
        self.reads[app] = self.reads.get(app, 0) + 1
        document = await fetcher.get_json(OPENAPI_PATHS[app], self._timeout)
        result = missing_from(self._routes_for(app), document)
        if result is not None:
            self._missing[app] = result

    def wrap(
        self, app: str, fetcher: _Fetcher, probe: Callable[[], Awaitable[tuple[bool, str]]]
    ) -> Callable[[], Awaitable[tuple[bool, str]]]:
        """``probe`` followed, on the first success, by this check (the detector's loop runs it)."""

        async def checked_probe() -> tuple[bool, str]:
            ok, reason = await probe()
            if ok and not self.checked(app):
                await self.run(app, fetcher)
            return ok, reason

        return checked_probe
