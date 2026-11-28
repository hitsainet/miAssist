"""The recorded scenarios: every Core tool and each of its outcomes, over fake apps (001 FTASKS
9.3, 10.5, 12.6). One list, read by the result-validation test, the side-effect test and the log
test, so a new outcome is covered by all three at once.

``seed(fakes, empty=...)`` answers every overview and approval route the way the apps do;
``SCENARIOS`` names (installed set, tool, arguments, how the fakes are prepared).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from tests.support import response_shapes as rs
from tests.support import shapes
from tests.support.fake_apps import FakeApp, all_fakes

APPS = ("miworkbench", "miserver", "midataworks", "miforge")
#: An argument value whose URL, JSON and percent-encoded forms all differ from its raw form.
ENCODED_ID = "fx appr/öval 1"


def answer(app: str, path: str, /, **fields: Any) -> Any:
    """``GET path``'s 200 answer as ``app`` sends it: ``fields`` plus everything the app always
    sends, checked against the vendored shape (``tests/support/shapes.py``)."""
    return shapes.instance(app, f"GET {path}", 200, **fields)


def answer_rows(app: str, path: str, rows: list[dict[str, Any]], /) -> list[Any]:
    """The same for a route that answers a bare list: each row completed and checked."""
    found = shapes.schema(app, f"GET {path}", 200)
    assert found is not None, f"{app} GET {path} has no vendored shape"
    filled = rs.fill(found, rows)
    assert not rs.check(found, filled), rs.check(found, filled)
    assert isinstance(filled, list)
    return filled


def _miworkbench_page(rows: list[dict[str, Any]], **paging: Any) -> dict[str, Any]:
    """miWorkbench's ``pagination`` (``models.py``/``datasets.py``: page, limit, total,
    total_pages, has_next, has_prev; ``saes.py``: skip, limit, total, has_more)."""
    return {"limit": 3, "total": len(rows), **paging}


def _miserver(data: Any) -> dict[str, Any]:
    """miServer's ``ApiResponse`` envelope: ``success``, ``data`` and a null ``error``."""
    return {"success": True, "data": data, "error": None}


def _probe_status(**counts: int) -> dict[str, Any]:
    return {"max_armed": 64, **counts}


#: Overview fix (2026-11-27): every answer is one the app sends, built from its vendored shape.
#: Before, each was invented (``{"items": [...]}`` for miWorkbench, which sends ``data`` and
#: ``pagination``; ``{"items": [...]}`` for miForge's checkpoints, which sends ``checkpoints``,
#: ``count`` and ``total``), so the overview agreed with its fakes by construction while it
#: miscounted miForge's checkpoints and missed miWorkbench's totals.
POPULATED: dict[str, list[tuple[str, Any]]] = {
    "miworkbench": [
        (
            "/api/v1/models",
            answer(
                "miworkbench",
                "/api/v1/models",
                data=[{"name": "fx-model"}],
                pagination=_miworkbench_page([{}], page=1),
            ),
        ),
        (
            "/api/v1/saes",
            answer(
                "miworkbench",
                "/api/v1/saes",
                data=[{"name": "fx-sae"}],
                pagination=_miworkbench_page([{}], skip=0),
            ),
        ),
        (
            "/api/v1/datasets",
            answer(
                "miworkbench",
                "/api/v1/datasets",
                data=[{"name": "fx-data"}],
                pagination=_miworkbench_page([{}], page=1),
            ),
        ),
        (
            "/api/v1/probe-monitors/probes",
            answer_rows(
                "miworkbench",
                "/api/v1/probe-monitors/probes",
                [{"id": "pm_fx", "created_at": shapes.WHEN}],
            ),
        ),
    ],
    "miserver": [
        ("/api/models", answer("miserver", "/api/models", **_miserver([{"name": "fx-model"}]))),
        (
            "/api/probes/status",
            answer(
                "miserver",
                "/api/probes/status",
                **_miserver(_probe_status(armed_count=1, imported_count=1, events_recorded=3)),
            ),
        ),
        (
            "/api/clusters",
            answer(
                "miserver",
                "/api/clusters",
                **_miserver({"active_cluster_id": None, "clusters": [{"name": "fx-cluster"}]}),
            ),
        ),
    ],
    "midataworks": [
        (
            "/api/v1/datasets",
            answer(
                "midataworks",
                "/api/v1/datasets",
                items=[{"name": "fx-dataset"}],
                total=1,
                page=1,
                limit=200,
            ),
        ),
        (
            "/api/v1/versions",
            answer(
                "midataworks",
                "/api/v1/versions",
                items=[{"id": "fx-version"}],
                total=1,
                page=1,
                limit=3,
            ),
        ),
    ],
    "miforge": [
        # miForge's real run row (``runs_index.run_row``): ``run_id``, never ``name`` or ``id``
        (
            "/api/v1/runs",
            answer(
                "miforge",
                "/api/v1/runs",
                runs=[{"run_id": "fx-run", "status": "succeeded"}],
                total=1,
                limit=3,
            ),
        ),
        (
            "/api/v1/packs",
            answer("miforge", "/api/v1/packs", packs=[{"pack_id": "fx-pack@1", "name": "fx-pack"}]),
        ),
        (
            "/api/v1/checkpoints",
            answer(
                "miforge",
                "/api/v1/checkpoints",
                checkpoints=[{"name": "fx-ckpt"}],
                count=1,
                total=1,
            ),
        ),
    ],
}
EMPTY: dict[str, list[tuple[str, Any]]] = {
    "miworkbench": [
        (
            "/api/v1/models",
            answer(
                "miworkbench",
                "/api/v1/models",
                data=[],
                pagination=_miworkbench_page([], page=1),
            ),
        ),
        (
            "/api/v1/saes",
            answer(
                "miworkbench", "/api/v1/saes", data=[], pagination=_miworkbench_page([], skip=0)
            ),
        ),
        (
            "/api/v1/datasets",
            answer(
                "miworkbench",
                "/api/v1/datasets",
                data=[],
                pagination=_miworkbench_page([], page=1),
            ),
        ),
        ("/api/v1/probe-monitors/probes", []),
    ],
    "miserver": [
        ("/api/models", answer("miserver", "/api/models", **_miserver([]))),
        (
            "/api/probes/status",
            answer("miserver", "/api/probes/status", **_miserver(_probe_status())),
        ),
        (
            "/api/clusters",
            answer(
                "miserver",
                "/api/clusters",
                **_miserver({"active_cluster_id": None, "clusters": []}),
            ),
        ),
    ],
    "midataworks": [
        (
            "/api/v1/datasets",
            answer("midataworks", "/api/v1/datasets", items=[], total=0, page=1, limit=200),
        ),
        (
            "/api/v1/versions",
            answer("midataworks", "/api/v1/versions", items=[], total=0, page=1, limit=3),
        ),
    ],
    "miforge": [
        ("/api/v1/runs", answer("miforge", "/api/v1/runs", runs=[], total=0, limit=3)),
        ("/api/v1/packs", answer("miforge", "/api/v1/packs", packs=[])),
        (
            "/api/v1/checkpoints",
            answer("miforge", "/api/v1/checkpoints", checkpoints=[], count=0, total=0),
        ),
    ],
}
APPROVAL_PATHS = {
    "miworkbench": "/api/v1/mcp/approvals/{request_id}",
    "miserver": "/api/approvals/{approval_id}",
    "midataworks": "/api/v1/approvals/{approval_id}",
    "miforge": "/api/v1/approvals/{approval_id}",
}


def seed(fakes: dict[str, FakeApp], *, empty: bool = False) -> dict[str, FakeApp]:
    table = EMPTY if empty else POPULATED
    for app, answers in table.items():
        for path, body in answers:
            fakes[app].on("GET", path, body)
        status = "approved" if app == "miworkbench" else "executing"
        fakes[app].on(
            "GET",
            APPROVAL_PATHS[app],
            lambda r, status=status: {
                "id": next(iter(r.path_params.values())),
                "status": status,
                "action": "fx_action",
            },
        )
    return fakes


Prepare = Callable[[dict[str, FakeApp], Any], None]


def refuse_overview(app: str, keep: int = 0) -> Prepare:
    """Every overview read of ``app`` after the first ``keep`` answers the app's own 403 envelope
    (R2 review fix OR2-001-4: a refused read is unknown, never empty)."""

    def prepare(fakes: dict[str, FakeApp], _deps: Any) -> None:
        fake = fakes[app]
        for path, _ in POPULATED[app][keep:]:
            fake.on("GET", path, lambda _r, f=fake: f.error(403, "forbidden", "not allowed"))

    return prepare


#: An overview answer in an envelope miAssist does not know (R3 review fix OR3-001-2).
UNKNOWN_SHAPE: Any = {"results_v2": {"rows": "moved"}, "ok": True}


def unreadable_overview(app: str, keep: int = 0) -> Prepare:
    """Every overview read of ``app`` after the first ``keep`` answers 200 in an unknown shape
    (R3 review fix OR3-001-2: an unreadable read is unknown, never empty)."""

    def prepare(fakes: dict[str, FakeApp], _deps: Any) -> None:
        for path, _ in POPULATED[app][keep:]:
            fakes[app].on("GET", path, UNKNOWN_SHAPE)

    return prepare


def _down(app: str) -> Prepare:
    def prepare(_fakes: dict[str, FakeApp], deps: Any) -> None:
        deps.runtime.detector.mark_unreachable(app, "connection refused")

    return prepare


@dataclass(frozen=True)
class Scenario:
    id: str
    installed: tuple[str, ...]
    tool: str
    args: dict[str, Any]
    empty: bool = False
    prepare: Prepare | None = None
    #: The scenario answers a tool error (isError) by design.
    error: bool = False
    tags: frozenset[str] = field(default_factory=frozenset)

    def fakes(self) -> dict[str, FakeApp]:
        return seed(all_fakes(), empty=self.empty)


def _core() -> list[Scenario]:
    out: list[Scenario] = []
    for topic in ("start", "apps", "playbooks", "approvals", "results", "glossary", "connect"):
        out.append(Scenario(f"guide-{topic}", APPS, "miassist_guide", {"topic": topic}))
    out.append(Scenario("guide-start-empty-set", (), "miassist_guide", {}))
    out += [
        Scenario("glossary-index", APPS, "miassist_glossary", {}),
        Scenario("glossary-entry", APPS, "miassist_glossary", {"term": "AUROC"}),
        Scenario("glossary-unknown", APPS, "miassist_glossary", {"term": "aurok"}, error=True),
        Scenario("status", APPS, "miassist_status", {}),
        Scenario("status-empty-set", (), "miassist_status", {}),
        Scenario("set-guidance-expert", APPS, "miassist_set_guidance", {"level": "expert"}),
        Scenario("set-guidance-beginner", APPS, "miassist_set_guidance", {"level": "beginner"}),
        Scenario("reset", APPS, "miassist_reset_my_settings", {}),
        Scenario("guide-playbook", APPS, "miassist_guide", {"playbook": "start-miforge"}),
        # an id with a slash, a space and a non-ASCII letter: its encoded forms differ from it, so the
        # log scan must look for them (R1 review fix OR1-001-10)
        Scenario(
            "approval-midataworks-encoded-id",
            ("midataworks",),
            "miassist_approval_status",
            {"app": "midataworks", "approval_id": ENCODED_ID},
        ),
        Scenario(
            "guide-playbook-absent",
            ("midataworks",),
            "miassist_guide",
            {"playbook": "start-miserver"},
        ),
        Scenario("guide-playbook-unknown", APPS, "miassist_guide", {"playbook": "no-such"}),
        Scenario("status-playbook", APPS, "miassist_status", {"playbook": "start-miforge"}),
        Scenario(
            "status-playbook-open",
            ("miforge",),
            "miassist_status",
            {"playbook": "start-miforge"},
            prepare=_down("miforge"),
        ),
        Scenario(
            "status-playbook-absent",
            ("miforge",),
            "miassist_status",
            {"playbook": "start-miserver"},
        ),
    ]
    for app in APPS:
        out += [
            Scenario(f"overview-{app}", APPS, "miassist_overview", {"app": app}),
            Scenario(f"overview-{app}-empty", (app,), "miassist_overview", {"app": app}, True),
            Scenario(
                f"overview-{app}-refused",
                (app,),
                "miassist_overview",
                {"app": app},
                True,
                prepare=refuse_overview(app),
            ),
            Scenario(
                f"overview-{app}-unreadable",
                (app,),
                "miassist_overview",
                {"app": app},
                True,
                prepare=unreadable_overview(app),
            ),
            Scenario(
                f"overview-{app}-down",
                (app,),
                "miassist_overview",
                {"app": app},
                prepare=_down(app),
            ),
            Scenario(
                f"approval-{app}",
                APPS,
                "miassist_approval_status",
                {"app": app, "approval_id": "fx-approval-1"},
            ),
            Scenario(
                f"approval-{app}-down",
                (app,),
                "miassist_approval_status",
                {"app": app, "approval_id": "fx-approval-1"},
                prepare=_down(app),
            ),
        ]
    return out


#: Playbook chains (003-005) and later Core tasks append their scenarios here.
EXTRA_SCENARIOS: list[Scenario] = []


def scenarios() -> list[Scenario]:
    return [*_core(), *EXTRA_SCENARIOS]


CORE_TOOLS = (
    "miassist_approval_status",
    "miassist_glossary",
    "miassist_guide",
    "miassist_overview",
    "miassist_reset_my_settings",
    "miassist_set_guidance",
    "miassist_status",
)


# -- running a scenario through the real ASGI app ------------------------------------------------

URLS = {f"{a}_url": f"http://{a}.test" for a in APPS}


def inner_app(test_client: Any) -> Any:
    """The FastAPI app inside the guard, the body cap and the key shim."""
    app = test_client.app
    while not hasattr(app, "state"):
        app = app.app
    return app


def wait_probed(test_client: Any, timeout_s: float = 3.0) -> None:
    """Wait until the lifespan's first probe has set every installed app's state."""
    import time

    deadline = time.monotonic() + timeout_s
    runtime = inner_app(test_client).state.runtime
    while time.monotonic() < deadline:
        if all(runtime.detector.snapshot(a).state != "unknown" for a in runtime.installed):
            return
        time.sleep(0.005)
    raise AssertionError("the detector's first probe did not finish")


@dataclass
class Run:
    result: dict[str, Any]
    fakes: dict[str, FakeApp]
    store: Any

    def app_requests(self) -> list[tuple[str, str, str, list[tuple[str, str]], Any]]:
        """Every request to an app except detection (health and the OpenAPI read)."""
        from miassist.installed.openapi_check import OPENAPI_PATHS

        skip = {"/api/health", *OPENAPI_PATHS.values()}
        return [
            (app, r.method, r.path, sorted(r.params.items()), r.body)
            for app, fake in sorted(self.fakes.items())
            for r in fake.requests
            if r.path not in skip
        ]


def run(
    scenario: Scenario,
    *,
    key: str | None = None,
    store: Any = None,
    level: str | None = None,
    headers: dict[str, str] | None = None,
) -> Run:
    """``scenario`` through ``/mcp`` (or ``/p/<key>/mcp``), the fakes cleared after detection.
    ``level`` (with a ``key``) is set first, through the tool."""
    from tests.support.app_factory import client
    from tests.support.http_mcp import call_tool
    from tests.support.memory_store import MemoryStore

    fakes = scenario.fakes()
    store = store if store is not None else MemoryStore()
    path = f"/p/{key}/mcp" if key else "/mcp"
    with client(
        store=store,
        transports={a: f.transport() for a, f in fakes.items()},
        apps=",".join(scenario.installed),
        **URLS,
    ) as test_client:
        wait_probed(test_client)
        if level is not None:
            assert key, "a level needs a key"
            call_tool(test_client, path, "miassist_set_guidance", {"level": level})
        if scenario.prepare is not None:
            scenario.prepare(fakes, inner_app(test_client).state.deps)
        for fake in fakes.values():
            fake.requests.clear()
        result = call_tool(test_client, path, scenario.tool, scenario.args, headers)
    return Run(result, fakes, store)
