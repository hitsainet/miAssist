"""The one outbound call site (PADR ADR-006; 001 FTASKS 4.1, FTID §3.3).

This is the ONLY module that imports httpx (``tests/unit/test_one_http_call_site.py``). Every app
call goes through ``AppClient.call``, which applies, in order, every rule that must never be
bypassed: the route registry, the snapshot gate, forbidden parameters (A20), the write floor (A25),
the Hub check (A23), the pending-approval cap (A24), file-first ids (A32), the person's reason
(FR-27), fixed per-route headers (A16), the floor limiter (A24, A37: a slot is taken only after
every refusal), then the send and the answer mapping.

The agent header is set on the CLIENT, never per call, so no adapter method can forget it.
"""

from __future__ import annotations

import json as jsonlib
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Final, Literal, Protocol
from urllib.parse import quote

import httpx

from miassist.errors import MiAssistError

if TYPE_CHECKING:
    from miassist.adapters.routes import RouteRegistry


class GateClass(StrEnum):
    """How an app gates a route (A16: one approval mechanism, no backend-gated class)."""

    READ = "read"
    APP_GATED = "app_gated"
    UNGATED_WRITE = "ungated_write"


class _Any:
    def __repr__(self) -> str:
        return "ANY"


#: A forbidden value meaning "may not be sent at all, whatever its value" (A20).
ANY: Final = _Any()

#: The agent header each app reads, and the value miAssist sends (PADR ADR-006's table).
HEADERS: Final[Mapping[str, tuple[str, str]]] = MappingProxyType(
    {
        "miworkbench": ("X-MiStudio-Agent", "miassist"),
        "miserver": ("X-miLLM-Agent", "agent:miassist"),
        "midataworks": ("X-Dataworks-Agent", "agent:miassist"),
        "miforge": ("X-Miforge-Agent", "agent:miassist"),
    }
)
#: The only header that ever carries an approval id, to miWorkbench's file-first routes (045 G4).
APPROVAL_ID_HEADER: Final = "X-MiStudio-Approval-Request"
#: The keys that need the person's own stated reason (FR-27).
ACKNOWLEDGE_KEYS: Final = frozenset({"acknowledge_unvalidated", "acknowledge_below_rung2"})
REQUEST_TIMEOUT_S: Final = 10.0


class ProgrammingError(RuntimeError):
    """A call miAssist's own code must never make (an unregistered route, a file-first route
    without an approved id, an ungated write outside the floor). Never caught by tools."""


@dataclass(frozen=True)
class Route:
    """One app route miAssist may call, with its gate class and every rule attached to it."""

    id: str
    app: str
    method: str
    path: str
    gate: GateClass
    purpose: str
    headers: Mapping[str, str] = field(default_factory=lambda: MappingProxyType({}))
    file_first: bool = False
    approval_action: str | None = None
    floor_entry: str | None = None
    gate_when: tuple[str, ...] = ()
    forbidden: Mapping[str, object] = field(default_factory=lambda: MappingProxyType({}))
    touches_hub: bool = False
    hub_repo_param: str | None = None
    hub_repo_type: Literal["dataset", "model"] | None = None
    budget: str | None = None
    gate_machinery: bool = False
    files_approval: bool = False
    #: The list route's maximum page (the pending cap's read, R3M-17), when it pages.
    page_limit: int | None = None
    #: A POST classed ``read`` because it only computes: no row, job, approval, file or paid call
    #: (PADR ADR-006, R2M-4; 003's training forecast). Only a read may carry it.
    computes_only: bool = False

    def may_file_approval(self) -> bool:
        """True when a call can make the app file an approval request (the pending cap applies)."""
        return self.gate is GateClass.APP_GATED or self.files_approval or bool(self.gate_when)


@dataclass(frozen=True)
class RawAnswer:
    """An app's HTTP answer, without httpx types (``results`` never sees httpx)."""

    status: int
    headers: Mapping[str, str]
    json: Any
    text: str


@dataclass(frozen=True)
class Resource:
    """A 2xx answer: the app's resource (or an accepted job)."""

    app: str
    status: int
    body: Any


@dataclass(frozen=True)
class Pending:
    """An approval waiting for the app's operator (a contract ``approval`` object)."""

    app: str
    approval: dict[str, Any]


@dataclass(frozen=True)
class AppError:
    """The app's own refusal, with its code normalised for line 1 (A30)."""

    app: str
    status: int
    code: str
    message: str
    original: str


@dataclass(frozen=True)
class Handoff:
    """A step for the operator, not an error (``operator_action``; A14, A23, A24)."""

    app: str
    reason: str


@dataclass(frozen=True)
class Unavailable:
    """The app could not be reached; nothing was decided."""

    app: str
    reason: str


AppAnswer = Resource | Pending | AppError | Handoff | Unavailable

_APPROVED: Final = object()
_PUBLIC: Final = object()


@dataclass(frozen=True)
class ApprovedId:
    """An approval id a status read showed ``approved`` (A32). Only ``issue_approved_id`` makes one,
    and only ``adapters.miworkbench.file_first`` calls it."""

    id: str
    state: Mapping[str, Any]
    _seal: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._seal is not _APPROVED:
            raise ProgrammingError("an ApprovedId is made only by issue_approved_id()")


def issue_approved_id(approval_id: str, state: Mapping[str, Any]) -> ApprovedId:
    if state.get("status") != "approved":
        raise ProgrammingError("an approved id is issued only for a status read showing approved")
    return ApprovedId(approval_id, MappingProxyType(dict(state)), _APPROVED)


@dataclass(frozen=True)
class PublicCheck:
    """The result of the exact-repository public check (A23). Only ``issue_public_check`` makes one,
    and only ``hub.public_check.run_public_check`` calls it."""

    repo_id: str
    public: bool
    bytes: int | None
    licence: str | None
    _seal: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._seal is not _PUBLIC:
            raise ProgrammingError("a PublicCheck is made only by issue_public_check()")


def issue_public_check(
    repo_id: str, public: bool, size: int | None, licence: str | None
) -> PublicCheck:
    return PublicCheck(repo_id, public, size, licence, _PUBLIC)


class Snapshot(Protocol):
    """The detector's never-blocking view (``installed.detector.Detector``)."""

    def unreachable_reason(self, app: str) -> str | None: ...

    def mark_unreachable(self, app: str, reason: str) -> None: ...


class Limiter(Protocol):
    async def take(self, budget: str, scope: str | None) -> None: ...


class PendingCapCheck(Protocol):
    async def check(self, app: str, client: AppClient) -> None: ...


@dataclass
class CallGuards:
    """What ``AppClient.call`` consults besides the route itself."""

    registry: RouteRegistry
    snapshot: Snapshot
    limiter: Limiter
    pending_cap: PendingCapCheck
    missing_routes: Callable[[str], frozenset[str]] = lambda _app: frozenset()
    #: miWorkbench's large-import threshold (A24, FR-30): ``MIASSIST_LARGE_IMPORT_BYTES``, equal to
    #: miDataworks' own ``IMPORT_CONFIRM_BYTES``. A larger or unknown checked size is the operator's.
    large_import_bytes: int = 50_000_000_000


def _param(name: str, params: Mapping[str, Any] | None, body: Any) -> tuple[bool, Any]:
    where, _, key = name.partition(".")
    if where == "query":
        source: Any = params or {}
    elif where == "body":
        source = body if isinstance(body, Mapping) else {}
    else:
        raise ProgrammingError(f"forbidden/hub parameter {name!r} must start query. or body.")
    return (key in source, source.get(key))


def _same(value: Any, refused: object) -> bool:
    if refused is ANY:
        return True
    return bool(value == refused)


def _acknowledgements(node: Any) -> bool:
    if isinstance(node, Mapping):
        return any(k in ACKNOWLEDGE_KEYS for k in node) or any(
            _acknowledgements(v) for v in node.values()
        )
    if isinstance(node, list):
        return any(_acknowledgements(v) for v in node)
    return False


def expand_path(route: Route, path_params: Mapping[str, Any] | None) -> str:
    path = route.path
    for name, value in (path_params or {}).items():
        token = "{" + name + "}"
        if token not in path:
            raise ProgrammingError(f"{route.id} has no path parameter {name!r}")
        path = path.replace(token, quote(str(value), safe=""))
    if "{" in path:
        raise ProgrammingError(f"{route.id} is missing a path parameter: {route.path}")
    return path


class AppClient:
    """One app's HTTP client. Every request miAssist makes to that app goes through ``call``."""

    def __init__(
        self,
        app: str,
        base_url: str,
        guards: CallGuards,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        classify: Callable[[str, Route, RawAnswer], AppAnswer] | None = None,
    ) -> None:
        if app not in HEADERS:
            raise ProgrammingError(f"unknown app {app!r}")
        self.app = app
        self.guards = guards
        name, value = HEADERS[app]
        self._http = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            headers={name: value},
            timeout=REQUEST_TIMEOUT_S,
            transport=transport,
            follow_redirects=False,
        )
        if classify is None:
            from miassist.results.app_answers import classify as default_classify

            classify = default_classify
        self._classify = classify

    async def aclose(self) -> None:
        await self._http.aclose()

    async def probe_health(self, timeout_s: float) -> tuple[bool, str]:
        """``GET /api/health``: reachable on HTTP 200 with a JSON object body (001 FR-2)."""
        try:
            response = await self._http.get("/api/health", timeout=timeout_s)
        except httpx.TimeoutException:
            return False, "timeout"
        except httpx.ConnectError:
            return False, "connection refused"
        except httpx.HTTPError:
            return False, "transport error"
        if response.status_code != 200:
            return False, f"HTTP {response.status_code}"
        try:
            body = response.json()
        except ValueError:
            return False, "not JSON"
        if not isinstance(body, dict):
            return False, "not JSON"
        return True, "ok"

    async def get_json(self, path: str, timeout_s: float) -> Any:
        """A raw GET for the runtime OpenAPI check (no route registry: it reads the app's own
        published description). Returns the JSON body, or ``None`` on any failure."""
        try:
            response = await self._http.get(path, timeout=timeout_s)
            if response.status_code != 200:
                return None
            return response.json()
        except (httpx.HTTPError, ValueError):
            return None

    async def call(
        self,
        route: Route,
        *,
        path_params: Mapping[str, Any] | None = None,
        params: Mapping[str, Any] | None = None,
        json: Any = None,
        approval_id: ApprovedId | None = None,
        public_check: PublicCheck | None = None,
        person_reason: str | None = None,
        floor_scope: str | None = None,
    ) -> AppAnswer:
        guards = self.guards
        # 1 the route must be this app's registered route (identity), never a never-route
        guards.registry.require(route, self.app)
        if route.id in guards.missing_routes(self.app):
            raise MiAssistError(
                "app_route_missing",
                f"the running {self.app} does not publish the route this needs",
                fix="the app's version may differ from the one miAssist was built against",
            )
        # 2 a known-unreachable app gets no request
        reason = guards.snapshot.unreachable_reason(self.app)
        if reason is not None:
            return Unavailable(self.app, reason)
        # 3 forbidden parameters (A20): refused before sending
        for name, refused in route.forbidden.items():
            present, value = _param(name, params, json)
            if present and _same(value, refused):
                raise MiAssistError(
                    "forbidden_argument",
                    f"miAssist never sends {name.partition('.')[2]} on this call",
                    fix="leave it out; the app's operator does this step",
                )
        # 3b miDataworks: every source the call names must have been imported without a
        #    credential, read before anything is sent (OVN-miassist-core-32, OR3-022-1)
        if self.app == "midataworks":
            from miassist.adapters.midataworks import check_named_sources

            stopped = await check_named_sources(self, route, path_params, params, json)
            if stopped is not None:
                return stopped
        # 4 an ungated write must be a floor entry (A25)
        if route.gate is GateClass.UNGATED_WRITE:
            from miassist.adapters.routes import UNGATED_WRITES_ALLOWED

            if route.floor_entry not in UNGATED_WRITES_ALLOWED:
                raise ProgrammingError(f"{route.id} is an ungated write outside the write floor")
        # 5 a route that touches the Hub needs a passing exact-repository check (A23)
        if route.touches_hub:
            if route.hub_repo_param is None:
                raise ProgrammingError(f"{route.id} touches the Hub but names no repository param")
            _, repo = _param(route.hub_repo_param, params, json)
            if not (
                isinstance(public_check, PublicCheck)
                and public_check.public
                and public_check.repo_id == repo
            ):
                return Handoff(self.app, "hf_import_by_operator")
            # 5a miWorkbench imports past the threshold, or of unknown size, are the operator's
            #    (miDataworks applies its own threshold and answers import_confirmation_required)
            if self.app == "miworkbench" and (
                public_check.bytes is None or public_check.bytes > guards.large_import_bytes
            ):
                return Handoff(self.app, "large_import_by_operator")
        # 6 a call that may file an approval, without an approved id: the pending cap (A24)
        if route.may_file_approval() and approval_id is None:
            await guards.pending_cap.check(self.app, self)
        # 7 file-first routes only with an approved id; the id header only there (A18, A32)
        headers: dict[str, str] = {}
        if route.file_first:
            if not isinstance(approval_id, ApprovedId):
                raise ProgrammingError(f"{route.id} is file-first: call it only with an ApprovedId")
            headers[APPROVAL_ID_HEADER] = approval_id.id
        elif approval_id is not None:
            raise ProgrammingError(f"{route.id} is not file-first: an approval id is never sent")
        # 8 acknowledge_* needs the person's own reason (FR-27), on the body, in the query (miServer
        #   takes acknowledge_unvalidated as a query parameter; R1 review fix OR1-001-9) and on a
        #   filing's nested canonical payload
        acknowledged = _acknowledgements(json) or _acknowledgements(dict(params or {}))
        if acknowledged and not (person_reason and person_reason.strip()):
            raise MiAssistError(
                "needs_your_reason",
                "this needs your own reason for going ahead below the evidence bar",
                fix="say why, in your own words, and pass it as the reason",
            )
        # 9 fixed per-route headers under the agent header (refused at registration if they clash)
        merged = {**route.headers, **headers}
        # 9a the floor's rate slot, immediately before sending (A24, A37)
        if route.gate is GateClass.UNGATED_WRITE:
            await guards.limiter.take(route.budget or str(route.floor_entry), floor_scope)
        # 10 send
        url = expand_path(route, path_params)
        try:
            response = await self._http.request(
                route.method,
                url,
                params=dict(params) if params else None,
                content=None if json is None else jsonlib.dumps(json).encode(),
                headers={
                    **merged,
                    **({"content-type": "application/json"} if json is not None else {}),
                },
            )
        except (httpx.TimeoutException, httpx.ConnectError, httpx.RemoteProtocolError) as exc:
            reason = "timeout" if isinstance(exc, httpx.TimeoutException) else "connection refused"
            guards.snapshot.mark_unreachable(self.app, reason)
            return Unavailable(self.app, reason)
        try:
            body = response.json()
        except ValueError:
            body = None
        raw = RawAnswer(response.status_code, dict(response.headers), body, response.text)
        answer = self._classify(self.app, route, raw)
        if isinstance(answer, Unavailable):
            guards.snapshot.mark_unreachable(self.app, answer.reason)
        if self.app == "midataworks":
            from miassist.adapters.midataworks import screen_answer

            answer = screen_answer(route, answer)
        return answer


AsyncProbe = Callable[[], Awaitable[tuple[bool, str]]]


def probes_for(clients: Sequence[AppClient], timeout_s: float) -> dict[str, AsyncProbe]:
    """The detector's probe per app, through each app's own client."""

    def make(client: AppClient) -> AsyncProbe:
        async def probe() -> tuple[bool, str]:
            return await client.probe_health(timeout_s)

        return probe

    return {client.app: make(client) for client in clients}
