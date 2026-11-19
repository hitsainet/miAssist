"""The process's runtime: the installed set, one client per installed app, the detector and the
floor's bounds, built once from settings (001 FR-1, FR-2; PADR ADR-003, ADR-007).

``build_runtime`` makes no request; ``Runtime.start`` (called by the app's lifespan) starts the
detector's loop, and ``Runtime.stop`` stops it and closes the clients.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from miassist.adapters.base import AppClient, CallGuards, probes_for
from miassist.adapters.limits import FloorLimiter, PendingCap, limits_with_overrides
from miassist.adapters.routes import ROUTES, RouteRegistry
from miassist.config import InstalledSet, MiAssistSettings
from miassist.installed.detector import Detector
from miassist.installed.openapi_check import OpenApiCheck
from miassist.store.degrading import DegradingStore, Store
from miassist.store.sweep import Sweeper


@dataclass
class Runtime:
    settings: MiAssistSettings
    installed: InstalledSet
    clients: dict[str, AppClient]
    detector: Detector
    limiter: FloorLimiter
    pending_cap: PendingCap
    store: DegradingStore
    sweeper: Sweeper
    route_check: OpenApiCheck
    extras: dict[str, Any] = field(default_factory=dict)

    async def start(self) -> None:
        self.detector.start()
        self.sweeper.start()

    async def stop(self) -> None:
        await self.sweeper.stop()
        await self.detector.stop()
        for client in self.clients.values():
            await client.aclose()


def build_runtime(
    settings: MiAssistSettings,
    *,
    transports: Mapping[str, Any] | None = None,
    registry: RouteRegistry | None = None,
    store: Store,
) -> Runtime:
    installed = InstalledSet.from_settings(settings)
    limiter = FloorLimiter(limits_with_overrides(settings.floor_limits))
    cap = PendingCap(settings.max_pending_approvals)
    detector_holder: dict[str, Detector] = {}

    class _Snapshot:
        def unreachable_reason(self, app: str) -> str | None:
            return detector_holder["d"].unreachable_reason(app)

        def mark_unreachable(self, app: str, reason: str) -> None:
            detector_holder["d"].mark_unreachable(app, reason)

    guards = CallGuards(
        registry=registry or ROUTES,
        snapshot=_Snapshot(),
        limiter=limiter,
        pending_cap=cap,
        large_import_bytes=settings.large_import_bytes,
    )
    clients = {
        app: AppClient(
            app,
            str(settings.app_url(app)),
            guards,
            transport=(transports or {}).get(app),
        )
        for app in installed.sorted()
    }
    routes = registry or ROUTES
    route_check = OpenApiCheck(routes.for_app, timeout_s=settings.health_timeout_s)
    guards.missing_routes = route_check.missing
    probes = probes_for(list(clients.values()), settings.health_timeout_s)
    detector = Detector(
        {app: route_check.wrap(app, clients[app], probe) for app, probe in probes.items()},
        interval_s=settings.health_interval_s,
    )
    detector_holder["d"] = detector
    degrading = store if isinstance(store, DegradingStore) else DegradingStore(store)
    sweeper = Sweeper(degrading, settings.retention_days)
    return Runtime(
        settings, installed, clients, detector, limiter, cap, degrading, sweeper, route_check
    )
