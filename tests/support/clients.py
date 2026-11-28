"""AppClients over fake apps, with the real guards (001 tests)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from types import MappingProxyType

from miassist.adapters.base import ANY, AppClient, CallGuards, GateClass, Route
from miassist.adapters.limits import FloorLimiter, PendingCap
from miassist.adapters.routes import CORE_ROUTES, RouteRegistry
from tests.support.fake_apps import FakeApp


@dataclass
class StubSnapshot:
    """A detector stand-in: ``down`` maps app -> reason."""

    down: dict[str, str] = field(default_factory=dict)
    marked: list[tuple[str, str]] = field(default_factory=list)

    def unreachable_reason(self, app: str) -> str | None:
        return self.down.get(app)

    def mark_unreachable(self, app: str, reason: str) -> None:
        self.marked.append((app, reason))
        self.down[app] = reason


def _route(**kw: object) -> Route:
    return Route(**kw)  # type: ignore[arg-type]


#: Fixture routes on a SEPARATE registry, never in production ROUTES (V-2).
FIXTURE_ROUTES = (
    _route(
        id="miworkbench.fixture_start_gpu_job",
        app="miworkbench",
        method="POST",
        path="/api/v1/fixture/probe-runs/{probe_id}/start",
        gate=GateClass.APP_GATED,
        purpose="fixture GPU route (served by a fake with no gate of its own)",
        file_first=True,
        approval_action="start_probe_training_run",
    ),
    _route(
        id="miserver.fixture_import_cluster",
        app="miserver",
        method="POST",
        path="/api/clusters/import",
        gate=GateClass.UNGATED_WRITE,
        purpose="fixture cluster import",
        floor_entry="steering.import_cluster",
        forbidden=MappingProxyType({"query.activate": ANY}),
    ),
    _route(
        id="miserver.fixture_test_chat",
        app="miserver",
        method="POST",
        path="/v1/chat/completions",
        gate=GateClass.UNGATED_WRITE,
        purpose="fixture bounded test chat",
        floor_entry="steering.test_chat",
        headers=MappingProxyType({"X-miLLM-Load-Policy": "refuse"}),
    ),
    _route(
        id="midataworks.fixture_import",
        app="midataworks",
        method="POST",
        path="/api/v1/sources/hf",
        gate=GateClass.UNGATED_WRITE,
        purpose="fixture M16 import",
        floor_entry="import.hf_midataworks",
        forbidden=MappingProxyType({"body.access_token": ANY, "body.confirm_large": ANY}),
        touches_hub=True,
        hub_repo_param="body.repo_id",
        hub_repo_type="dataset",
    ),
    _route(
        id="midataworks.fixture_publish_checks",
        app="midataworks",
        method="POST",
        path="/api/v1/versions/{version_id}/publish-checks",
        gate=GateClass.APP_GATED,
        purpose="fixture publish checks (an operator action in production, A34)",
        forbidden=MappingProxyType({"body.repo_id": ANY}),
    ),
    _route(
        id="midataworks.fixture_build_version",
        app="midataworks",
        method="POST",
        path="/api/v1/versions",
        gate=GateClass.UNGATED_WRITE,
        purpose="fixture conditional gate (A19)",
        floor_entry="dataset.build_version",
        gate_when=("state:agent_label_plan_or_sensitivity_lowering",),
    ),
    # OVN-miassist-core-32: miDataworks source reads a playbook chain registers (004).
    _route(
        id="midataworks.fixture_list_sources",
        app="midataworks",
        method="GET",
        path="/api/v1/sources",
        gate=GateClass.READ,
        purpose="fixture source list",
    ),
    _route(
        id="midataworks.fixture_source_rows",
        app="midataworks",
        method="GET",
        path="/api/v1/sources/{source_id}/rows",
        gate=GateClass.READ,
        purpose="fixture source rows",
    ),
    _route(
        id="midataworks.fixture_source_profile",
        app="midataworks",
        method="GET",
        path="/api/v1/sources/{source_id}/profile",
        gate=GateClass.READ,
        purpose="fixture source preview (its profile)",
    ),
    _route(
        id="miforge.fixture_gated",
        app="miforge",
        method="POST",
        path="/api/v1/fixture/runs",
        gate=GateClass.APP_GATED,
        purpose="fixture server-executed gated route",
    ),
)


def test_registry() -> RouteRegistry:
    return RouteRegistry(CORE_ROUTES + FIXTURE_ROUTES)


test_registry.__test__ = False  # type: ignore[attr-defined]


def client_for(
    fake: FakeApp,
    *,
    registry: RouteRegistry | None = None,
    snapshot: StubSnapshot | None = None,
    limiter: FloorLimiter | None = None,
    cap: PendingCap | None = None,
    missing: Callable[[str], frozenset[str]] | None = None,
) -> AppClient:
    guards = CallGuards(
        registry=registry or test_registry(),
        snapshot=snapshot or StubSnapshot(),
        limiter=limiter or FloorLimiter(),
        pending_cap=cap or PendingCap(),
    )
    if missing is not None:
        guards.missing_routes = missing
    return AppClient(fake.app, f"http://{fake.app}.test", guards, transport=fake.transport())


def no_pending(fake: FakeApp) -> FakeApp:
    """Give ``fake`` an empty pending-approval list (the cap reads it before any filing)."""
    paths = {
        "miworkbench": "/api/v1/mcp/approvals",
        "miserver": "/api/approvals",
        "midataworks": "/api/v1/approvals",
        "miforge": "/api/v1/approvals",
    }
    return fake.on("GET", paths[fake.app], {"approvals": [], "total": 0})
