"""The route registry: the authority for what miAssist calls (PADR ADR-006; FTID §3.3-§3.4).

Every guard reads this registry, never the source. It holds:

- ``ROUTES``: Core's registered routes (003-005 add theirs through ``ROUTES.register``);
- ``UNGATED_WRITES_ALLOWED``: exactly the PADR's fourteen write-floor entries (M12, M16; A25, A34);
- ``NEVER_ROUTES``: what miAssist never calls (A14), refused at registration;
- ``REQUIRED_FORBIDDEN``: the parameters a route MUST refuse to send (A20);
- ``MISERVER_CONDITIONAL_GATES``: miServer's conditionally gated routes, never registered (A19);
- ``classify_marker``: how an app's published gate marker classifies a route (A19, A33).
"""

from __future__ import annotations

import re
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Final

from miassist.adapters.base import ANY, HEADERS, GateClass, ProgrammingError, Route
from miassist.playbooks.detector_probe.routes import DETECTOR_ROUTES

#: The write floor (M12 and M16, operator 2026-11-15; narrowed by A25 and A34): PADR ADR-006's
#: fourteen entry ids. Each chain binds its own routes to these ids (a ``floor_entry`` column).
UNGATED_WRITES_ALLOWED: Final[frozenset[str]] = frozenset(
    {
        "detector.create_behaviour",
        "detector.register_views",
        "detector.create_nonsense_text",
        "steering.import_probe",
        "dataset.create",
        "dataset.save_recipe",
        "dataset.build_version",
        "dataset.build_files",
        "steering.save_profile",
        "steering.import_cluster",
        "steering.import_circuit",
        "steering.test_chat",
        "import.hf_miworkbench",
        "import.hf_midataworks",
    }
)

#: miServer's routes whose gate has a predicate (A19, R2M-12). miServer publishes no
#: ``x-approval-when``, so none of them is ever registered.
MISERVER_CONDITIONAL_GATES: Final[frozenset[tuple[str, str]]] = frozenset(
    {
        ("PUT", "/api/environment"),
        ("PUT", "/api/environment/{key}"),
        ("DELETE", "/api/environment/{key}"),
        ("POST", "/api/rule-sets/import"),
    }
)

#: The (app, method, path) entries whose ``forbidden`` declaration is mandatory (A20).
REQUIRED_FORBIDDEN: Final[Mapping[tuple[str, str, str], Mapping[str, object]]] = MappingProxyType(
    {
        ("miserver", "POST", "/api/clusters/import"): {"query.activate": ANY},
        ("miserver", "POST", "/api/clusters/hub/import"): {"body.activate": ANY},
        ("midataworks", "POST", "/api/v1/versions/{version_id}/publish-checks"): {
            "body.repo_id": ANY
        },
        ("miworkbench", "POST", "/api/v1/datasets/download"): {"body.access_token": ANY},
        ("midataworks", "POST", "/api/v1/sources/hf"): {
            "body.access_token": ANY,
            "body.confirm_large": ANY,
        },
        ("midataworks", "POST", "/api/v1/sources/hf/preview"): {"body.access_token": ANY},
    }
)


@dataclass(frozen=True)
class NeverRoute:
    """A pattern of routes miAssist never calls (A14), with the reason."""

    id: str
    app: str | None
    method: str | None
    path: re.Pattern[str]
    reason: str

    def matches(self, app: str, method: str, path: str) -> bool:
        return (
            (self.app is None or self.app == app)
            and (self.method is None or self.method == method)
            and self.path.fullmatch(path) is not None
        )


def _never(id: str, app: str | None, method: str | None, path: str, reason: str) -> NeverRoute:
    return NeverRoute(id, app, method, re.compile(path), reason)


#: A14's never-registered routes. Each pattern must match at least one route in the app's full
#: route index (``tests/unit/test_never_routes.py``), so a renamed route cannot slip past.
NEVER_ROUTES: Final[tuple[NeverRoute, ...]] = (
    _never(
        "miserver.probe_arm",
        "miserver",
        "POST",
        r"/api/probes/\{probe_id\}/arm",
        "arming a probe is the operator's step (a probe_arm gate is a miServer follow-up)",
    ),
    _never(
        "miserver.behaviour_arm",
        "miserver",
        "POST",
        r"/api/probes/behaviours/\{key\}/arm",
        "arming a behaviour is the operator's step",
    ),
    _never(
        "miserver.cluster_activation",
        "miserver",
        None,
        r"/api/clusters/\{[a-z_]+\}/(activate|deactivate|intensity)",
        "activating, deactivating or setting a cluster's intensity is the operator's step",
    ),
    _never(
        "miserver.circuit_activation",
        "miserver",
        None,
        r"/api/circuits/\{[a-z_]+\}/(activate|deactivate|intensity)",
        "activating, deactivating or setting a circuit's intensity is the operator's step",
    ),
    _never(
        "miserver.hub",
        "miserver",
        None,
        r"/api/(probes|clusters)/hub(/.*)?",
        "miServer's Hub routes read with its stored credential for every caller",
    ),
    _never(
        "midataworks.generation_start",
        "midataworks",
        "POST",
        r"/api/v1/generation-runs(/\{[a-z_]+\}/(start|resume))?",
        "a generation run makes paid calls; the operator starts it",
    ),
    # miForge's editor-endpoint change and remove are the operator's alone: an agent gets 403
    # wsp_endpoint_operator_only (miForge backend/src/api/v1/endpoints/wsp_endpoints.py,
    # operator_router), and they are exempt from miForge's MCP surface for good (018 P2; OVN-018-1).
    # The register has been an agent PROPOSAL since miForge d80e333 (2026-11-20): always gated as
    # wsp_endpoint_register, local and keyless only, run by miForge once approved. miAssist offers
    # no such proposal, so it stays a never-route until the operator says otherwise (the 1124
    # re-pin, OVN-miassist-1124-1).
    _never(
        "miforge.wsp_endpoint_register",
        "miforge",
        "POST",
        r"/api/v1/wsp/endpoints",
        "miAssist does not propose editor endpoints: in miForge an agent's proposal waits for the "
        "operator (wsp_endpoint_register), and offering it is the operator's decision",
    ),
    _never(
        "miforge.wsp_endpoint_change",
        "miforge",
        "PATCH",
        r"/api/v1/wsp/endpoints/\{endpoint_id\}",
        "changing an editor endpoint's action protocol or context window is the operator's step",
    ),
    _never(
        "miforge.wsp_endpoint_remove",
        "miforge",
        "DELETE",
        r"/api/v1/wsp/endpoints/\{endpoint_id\}",
        "removing an editor endpoint is the operator's step in miForge",
    ),
    _never(
        "any.token_write",
        None,
        None,
        r".*(hf[-_]token|/tokens?)(/.*)?",
        "miAssist never sets a Hugging Face token",
    ),
    _never(
        "any.decide",
        None,
        None,
        r".*/(approve|deny|reject|approve-batch|revoke)",
        "miAssist never decides an approval, and never revokes one (R2 review fix OR2-001-9)",
    ),
    _never(
        "any.approval_archive",
        None,
        None,
        r".*/approvals/\{[a-z_0-9]+\}/(archive|unarchive)",
        "archiving an approval is the operator's step (R2 review fix OR2-001-9)",
    ),
    _never(
        "miworkbench.consume",
        "miworkbench",
        "POST",
        r"/api/v1/mcp/approvals/\{[a-z_]+\}/consume",
        "the GPU route consumes the id itself (045 FR-13)",
    ),
)

#: Decide routes are never registered, whatever their app (ADR-006).
DECIDE_SUFFIXES: Final = ("/approve", "/deny", "/reject", "/approve-batch", "/revoke")

#: miDataworks' gate-marker vocabulary (022's ``WHEN_MARKERS``).
WHEN_ALWAYS: Final = "always"

#: The marker naming the other action a gated call can wait as (miForge ``mark_gated_routes``).
ESCALATION: Final = "x-approval-escalation"


class UnknownGate(ProgrammingError):
    """A marked route whose gate condition miAssist cannot classify (A19, A33, R2M-10)."""


def classify_marker(
    app: str, method: str, path: str, operation: Mapping[str, Any]
) -> GateClass | None:
    """How an app's published gate marker classifies a route, or ``None`` when unmarked.

    - miDataworks: from ``x-approval-when`` alone (A33): ``always`` is ``app_gated``; ``field:``/
      ``state:`` tokens are a conditional gate, ``ungated_write`` with a floor entry and a
      ``gate_when`` equal to the tokens; a marked route without it raises ``UnknownGate``.
    - miServer: a marked route in ``MISERVER_CONDITIONAL_GATES`` raises; any other is ``app_gated``.
    - miForge: a marked route raises (it publishes no ``x-approval-when``; R2M-10).
    - miWorkbench: classified from the vendored per-route vectors, not markers (A38).

    Whatever the app, a marked route that also publishes ``x-approval-escalation`` raises: its call
    may wait as that other action instead, chosen per request, so miAssist cannot say which
    approval a call files (FU-10; miForge's ``gpu_start`` -> ``hotupdate_attach`` and
    ``wsp_session`` -> ``wsp_session_external``).
    """
    if "x-approval-action" not in operation:
        return None
    if ESCALATION in operation:
        raise UnknownGate(
            f"{method} {path}: may wait as {operation[ESCALATION]!r} instead of "
            f"{operation['x-approval-action']!r}, chosen per request (x-approval-escalation)"
        )
    if app == "midataworks":
        when = operation.get("x-approval-when")
        if when is None:
            raise UnknownGate(f"{method} {path}: marked without x-approval-when")
        tokens = tuple(t.strip() for t in str(when).split(",") if t.strip())
        if tokens == (WHEN_ALWAYS,):
            return GateClass.APP_GATED
        if tokens and all(t.startswith(("field:", "state:")) for t in tokens):
            return GateClass.UNGATED_WRITE
        raise UnknownGate(f"{method} {path}: unknown x-approval-when {when!r}")
    if app == "miserver":
        if (method, path) in MISERVER_CONDITIONAL_GATES:
            raise UnknownGate(f"{method} {path}: a conditional miServer gate (A19)")
        return GateClass.APP_GATED
    if app == "miforge":
        raise UnknownGate(f"{method} {path}: miForge publishes no x-approval-when (R2M-10)")
    return None


def when_tokens(operation: Mapping[str, Any]) -> tuple[str, ...]:
    when = operation.get("x-approval-when")
    return tuple(t.strip() for t in str(when).split(",") if t.strip()) if when else ()


class RouteRegistry:
    """Routes by id, each checked when registered."""

    def __init__(self, routes: tuple[Route, ...] = ()) -> None:
        self._by_id: dict[str, Route] = {}
        for route in routes:
            self.register(route)

    def register(self, route: Route) -> Route:
        check_registration(route)
        if route.id in self._by_id:
            raise ProgrammingError(f"route {route.id} registered twice")
        self._by_id[route.id] = route
        return route

    def require(self, route: Route, app: str) -> None:
        registered = self._by_id.get(route.id)
        if registered is not route or route.app != app:
            raise ProgrammingError(f"{route.id} is not a registered {app} route")

    def get(self, route_id: str) -> Route:
        return self._by_id[route_id]

    def for_app(self, app: str) -> list[Route]:
        return [r for r in self._by_id.values() if r.app == app]

    def __iter__(self) -> Iterator[Route]:
        return iter(self._by_id.values())

    def __len__(self) -> int:
        return len(self._by_id)


def check_registration(route: Route) -> None:
    """Every rule a route must satisfy to be registered at all."""
    if route.app not in HEADERS:
        raise ProgrammingError(f"{route.id}: unknown app {route.app!r}")
    if not route.id.startswith(route.app + "."):
        raise ProgrammingError(f"{route.id}: a route id starts with its app id")
    for never in NEVER_ROUTES:
        if never.matches(route.app, route.method, route.path):
            raise ProgrammingError(f"{route.id} is a never-route ({never.id}): {never.reason}")
    if route.app == "miserver" and (route.method, route.path) in MISERVER_CONDITIONAL_GATES:
        raise UnknownGate(f"{route.id}: a conditional miServer gate is never registered (A19)")
    agent_header = HEADERS[route.app][0].lower()
    if any(name.lower() == agent_header for name in route.headers):
        raise ProgrammingError(f"{route.id}: a fixed header may not replace the agent header")
    required = REQUIRED_FORBIDDEN.get((route.app, route.method, route.path))
    if required is not None:
        for name, value in required.items():
            if name not in route.forbidden or route.forbidden[name] is not value:
                raise ProgrammingError(f"{route.id} must forbid {name} (A20)")
    if route.gate is GateClass.UNGATED_WRITE:
        if route.floor_entry not in UNGATED_WRITES_ALLOWED:
            raise ProgrammingError(f"{route.id}: an ungated write needs a write-floor entry (A25)")
    elif route.floor_entry is not None or route.budget is not None:
        raise ProgrammingError(f"{route.id}: only an ungated write has a floor entry or budget")
    if route.gate_when and route.gate is not GateClass.UNGATED_WRITE:
        raise ProgrammingError(f"{route.id}: a conditional gate is an ungated write (A19)")
    if route.file_first and (
        route.app != "miworkbench"
        or route.gate is not GateClass.APP_GATED
        or not route.approval_action
    ):
        raise ProgrammingError(
            f"{route.id}: file-first is a miWorkbench app-gated route with an action"
        )
    if route.touches_hub:
        if route.hub_repo_param is None:
            raise ProgrammingError(f"{route.id}: a Hub route names its repository parameter")
        if route.hub_repo_type != "dataset":
            raise ProgrammingError(f"{route.id}: only dataset repositories have a public check")
    if route.computes_only and (route.gate is not GateClass.READ or route.method != "POST"):
        raise ProgrammingError(f"{route.id}: only a POST read may be marked computes-only")
    if (
        route.gate is GateClass.READ
        and route.method != "GET"
        and not (route.gate_machinery or route.computes_only)
    ):
        raise ProgrammingError(f"{route.id}: a read that is not a GET must say why (R2M-4)")
    if route.method not in ("GET", "POST", "PUT", "PATCH", "DELETE"):
        raise ProgrammingError(f"{route.id}: unknown method {route.method}")


def _read(id: str, app: str, path: str, purpose: str, **kw: Any) -> Route:
    return Route(
        id=id, app=app, method="GET", path=path, gate=GateClass.READ, purpose=purpose, **kw
    )


#: Core's registry (FTID §3.4; paths from the apps' code, verified by the pins).
CORE_ROUTES: Final[tuple[Route, ...]] = (
    _read("miworkbench.health", "miworkbench", "/api/health", "detection"),
    _read("miworkbench.list_models", "miworkbench", "/api/v1/models", "overview"),
    _read("miworkbench.list_saes", "miworkbench", "/api/v1/saes", "overview"),
    _read("miworkbench.list_datasets", "miworkbench", "/api/v1/datasets", "overview"),
    _read("miworkbench.list_probes", "miworkbench", "/api/v1/probe-monitors/probes", "overview"),
    Route(
        id="miworkbench.file_approval",
        app="miworkbench",
        method="POST",
        path="/api/v1/mcp/approvals",
        gate=GateClass.READ,
        purpose="file a GPU approval in miWorkbench's queue (A32); writes only the request",
        gate_machinery=True,
        files_approval=True,
    ),
    _read(
        "miworkbench.get_approval",
        "miworkbench",
        "/api/v1/mcp/approvals/{request_id}",
        "approval status",
        gate_machinery=True,
    ),
    _read(
        "miworkbench.list_approvals",
        "miworkbench",
        "/api/v1/mcp/approvals",
        "the pending cap",
        gate_machinery=True,
        page_limit=500,
    ),
    _read("miserver.health", "miserver", "/api/health", "detection"),
    _read("miserver.list_models", "miserver", "/api/models", "overview"),
    _read("miserver.probe_status", "miserver", "/api/probes/status", "overview (counts only)"),
    _read("miserver.list_clusters", "miserver", "/api/clusters", "overview"),
    _read("miserver.get_approval", "miserver", "/api/approvals/{approval_id}", "approval status"),
    _read("miserver.list_approvals", "miserver", "/api/approvals", "the pending cap"),
    _read("midataworks.health", "midataworks", "/api/health", "detection"),
    _read("midataworks.list_datasets", "midataworks", "/api/v1/datasets", "overview"),
    _read("midataworks.list_versions", "midataworks", "/api/v1/versions", "overview"),
    _read(
        "midataworks.get_approval",
        "midataworks",
        "/api/v1/approvals/{approval_id}",
        "approval status",
    ),
    _read("midataworks.list_approvals", "midataworks", "/api/v1/approvals", "the pending cap"),
    _read(
        "midataworks.get_source",
        "midataworks",
        "/api/v1/sources/{source_id}",
        "how a named source was imported, before any call uses it (OVN-miassist-core-32)",
    ),
    # R3 review fix (OR3-int-1), 2026-11-16: a version's whole lineage as miDataworks records it
    # (the manifest's transitive ``sources``; ``/lineage``'s ``rule_sources``), for Core's screen.
    _read(
        "midataworks.get_version_manifest",
        "midataworks",
        "/api/v1/versions/{version_id}/manifest",
        "every source a version's lineage reaches, before miAssist uses the version",
    ),
    _read(
        "midataworks.get_version_lineage",
        "midataworks",
        "/api/v1/versions/{version_id}/lineage",
        "a version's input versions and rule_source ancestors, before miAssist uses it",
    ),
    _read("miforge.health", "miforge", "/api/health", "detection"),
    _read("miforge.list_runs", "miforge", "/api/v1/runs", "overview"),
    _read("miforge.list_packs", "miforge", "/api/v1/packs", "overview"),
    _read("miforge.list_checkpoints", "miforge", "/api/v1/checkpoints", "overview"),
    _read("miforge.get_approval", "miforge", "/api/v1/approvals/{approval_id}", "approval status"),
    _read("miforge.list_approvals", "miforge", "/api/v1/approvals", "the pending cap"),
    Route(
        id="midataworks.hf_search",
        app="midataworks",
        method="POST",
        path="/api/v1/sources/hf/search",
        gate=GateClass.UNGATED_WRITE,
        purpose="the exact-repository public check and the filtered candidate search (A23, A37)",
        floor_entry="import.hf_midataworks",
        budget="hub.search",
    ),
    Route(
        id="midataworks.hf_preview",
        app="midataworks",
        method="POST",
        path="/api/v1/sources/hf/preview",
        gate=GateClass.UNGATED_WRITE,
        purpose="a public dataset's size and licence, after the public check (A23)",
        floor_entry="import.hf_midataworks",
        budget="hub.preview",
        gate_when=("field:body.access_token",),
        forbidden=MappingProxyType({"body.access_token": ANY}),
        touches_hub=True,
        hub_repo_param="body.repo_id",
        hub_repo_type="dataset",
    ),
)

#: Core's routes and each playbook chain's (003: ``DETECTOR_ROUTES``; 004 and 005 register theirs
#: through ``_register_chains`` below).
ROUTES: Final = RouteRegistry(CORE_ROUTES + DETECTOR_ROUTES)


def _register_chains(registry: RouteRegistry) -> None:
    """Playbook chains' routes (003-005), each checked by ``check_registration`` like Core's."""
    from miassist.adapters.dataset import DATASET_ROUTES
    from miassist.adapters.steering import ENABLED_GPU_ROWS, STEERING_ROUTES, gpu_routes

    for route in (*DATASET_ROUTES, *STEERING_ROUTES, *gpu_routes(ENABLED_GPU_ROWS)):
        registry.register(route)


_register_chains(ROUTES)
