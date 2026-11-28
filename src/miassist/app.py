"""The ASGI application (PADR ADR-003; Foundation tasks 2.1, 2.7, 9.1, 9.2).

``create_app(settings)`` builds one FastAPI app serving ``GET /health`` and the MCP streamable-HTTP
app at ``/mcp``, and wraps it in ``PublicHostGuard`` as the OUTERMOST layer (A21): nothing, not
even ``/health``, answers a request that came through the public proxy until push 001-P.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from importlib.resources.abc import Traversable
from typing import Any

from fastapi import FastAPI
from starlette.types import ASGIApp

from miassist.config import MiAssistSettings
from miassist.guidance.loader import Guidance
from miassist.runtime import build_runtime
from miassist.server.build import build_mcp_app, build_server
from miassist.server.keyshim import KeyShim
from miassist.server.specs import Deps
from miassist.store.db import Database
from miassist.store.degrading import Store
from miassist.store.repository import SqlStore
from miassist.tools import all_specs
from miassist.web.body_cap import BodyCap
from miassist.web.exposure import PublicHostGuard
from miassist.web.health import make_health
from miassist.web.pages import make_router


def create_app(
    settings: MiAssistSettings,
    *,
    database: Database | None = None,
    transports: Mapping[str, Any] | None = None,
    store: Store | None = None,
    guidance: Guidance | None = None,
    definitions: Traversable | None = None,
) -> ASGIApp:
    """The whole service as one ASGI app. ``transports`` (tests only) route each app's client to a
    fake; ``guidance`` and ``definitions`` (tests only) replace the shipped guidance and playbook
    definitions."""
    db = database if database is not None else Database(settings.database_url)
    runtime = build_runtime(settings, transports=transports, store=store or SqlStore(db))
    deps = Deps(runtime=runtime, guidance=guidance or Guidance())
    mcp = build_server(deps, all_specs(), definitions=definitions)
    mcp_app = build_mcp_app(mcp, settings)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        await runtime.start()
        async with mcp.session_manager.run():
            try:
                yield
            finally:
                await runtime.stop()
                await db.dispose()

    api = FastAPI(
        title="miAssist", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None
    )
    api.state.mcp = mcp
    api.state.database = db
    api.state.runtime = runtime
    api.state.deps = deps

    def app_states() -> dict[str, str]:
        return {
            app: runtime.detector.public_reason(runtime.detector.snapshot(app))
            for app in runtime.installed.sorted()
        }

    api.add_api_route(
        "/health",
        make_health(db.ping, app_states, runtime.route_check.all_missing),
        methods=["GET"],
        include_in_schema=False,
    )
    api.include_router(make_router(lambda: runtime))
    api.mount("/", mcp_app)
    return PublicHostGuard(BodyCap(KeyShim(api), settings.max_request_body_bytes))
