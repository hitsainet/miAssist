"""Stateful fakes of the three apps for the detector-probe playbook (003 FTID §8).

Built on Core's ``FakeApp`` (agent-header checks, request log). **Every answer is the app's real
shape** (R1 review fix OR1-pb-6 to OR1-pb-9, 2026-11-16): the ``World`` holds partial records as
tests write them, and each handler renders its answer through ``tests/support/response_shapes``
(``render``: the app's shape at a recorded commit, with every field the app always sends filled in).
``CheckedFake`` then checks the answer it is about to give against that shape; an invented or dropped
field, a value outside the app's enum, or a status the route never answers is a violation that the
``conftest`` fixture turns into a failing test.

A22 fixture rules: every id is an ``evalfx-`` fixture id or one this run created, the goal behaviour
is the non-DLP ``detector-refund``, and the "other" entries that must never reach a result are named
``other-…``. The fake miWorkbench gates its GPU routes as 045-A0 does (``core/approval_gate.py``): a
call without an approved id is refused 409 ``{status, reason}``, the approval is consumed BEFORE the
handler runs, and a refusal after the consume marks it ``failed`` (A40).
"""

from __future__ import annotations

import hashlib
import itertools
import json
from dataclasses import dataclass, field
from typing import Any

import httpx

from miassist.adapters.miworkbench import canonical_payload
from tests.support import dw_journey
from tests.support.fake_apps import FakeApp, Recorded
from tests.support.response_shapes import check, fill, schema_for

KEY = "detector-refund"
PM = "/api/v1/probe-monitors"
GPU_ROUTES = {
    ("POST", f"{PM}/runs"): "start_probe_training_run",
    ("POST", f"{PM}/probes/{{probe_id}}/evaluate"): "evaluate_probe_monitor",
    ("POST", f"{PM}/probes/{{probe_id}}/definition"): "build_probe_definition",
}
#: miWorkbench's ``MAX_UNSAMPLED_EVAL_ROWS`` (``schemas/probe_monitor.py:61`` at fb3ddce36).
MAX_UNSAMPLED_EVAL_ROWS = 20_000
DEFAULT_COUNTS = {"positive": 300, "negative": 700, "excluded": 0, "filtered_out": 0}

#: Every checked fake made in this process; the conftest fixture reads their violations.
CREATED: list[CheckedFake] = []


class CheckedFake(FakeApp):
    """A ``FakeApp`` whose every answer is checked against the app's vendored shape."""

    def __init__(self, app: str) -> None:
        super().__init__(app)
        self.shape_violations: list[str] = []
        self._departures: dict[str, str] = {}
        CREATED.append(self)

    def allow_departure(self, where: str, why: str) -> None:
        """One test's deliberate answer outside the app's vendored shape (e.g. a journey step a
        later version may add). ``why`` is required: every departure says what it stands for."""
        assert why.strip(), "a departure from the app's shape needs its reason"
        self._departures[where] = why

    def handle(self, request: httpx.Request) -> httpx.Response:
        response = super().handle(request)
        recorded = self.requests[-1]
        where = f"{self.app} {request.method} {recorded.template or recorded.path}"
        if recorded.path.endswith("openapi.json"):
            return (
                response  # Core's own probe of the app (detector), not an answer a playbook reads
            )
        if recorded.template is None:
            self.shape_violations.append(f"{where}: the fake does not model this route")
            return response
        schema = schema_for(self.app, request.method, recorded.template, response.status_code)
        if schema is None:
            self.shape_violations.append(
                f"{where} {response.status_code}: the app never answers this status here "
                "(nothing vendored in tests/fixtures/openapi)"
            )
            return response
        body = json.loads(response.content) if response.content else None
        self.shape_violations += [
            f"{where} {response.status_code}: {v}"
            for v in check(schema, body)
            if not any(v.startswith(d) for d in self._departures)
        ]
        return response


def render(app: str, route: str, status: int, partial: Any) -> Any:
    """``partial`` completed to ``app``'s real answer to ``route`` with ``status``."""
    method, template = route.split(" ", 1)
    schema = schema_for(app, method, template, status)
    if schema is None:
        raise KeyError(f"no vendored shape for {app} {route} {status}")
    return fill(schema, partial)


def dw_approval_view(row: dict[str, Any]) -> dict[str, Any]:
    """miDataworks' shared ``approval`` object for one stored request, as its gate and its approval
    reads compute it (``services/result_language.py:35-54`` ``approval_view`` at b10122e4, 022
    FR-022.3, .4): the row's own status, ``then`` always ``server_runs``. The real body carries it,
    and Core reads it first (``results/approvals.py`` ``unwrap``), so a fake that left it to ``fill``
    handed Core an id the app never filed (train A1's re-pin)."""
    return {
        "id": row["id"],
        "status": row["status"],
        "decide_in": "midataworks",
        "then": "server_runs",
        "summary": row.get("summary") or row["action"],
    }


def wb(route: str, status: int, partial: Any) -> httpx.Response:
    return httpx.Response(status, json=render("miworkbench", route, status, partial))


def dw(route: str, status: int, partial: Any) -> httpx.Response:
    return httpx.Response(status, json=render("midataworks", route, status, partial))


def sv(route: str, status: int, partial: Any) -> httpx.Response:
    return httpx.Response(status, json=render("miserver", route, status, partial))


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


@dataclass
class World:
    """Everything the three fakes hold; tests change it to reach a state."""

    behaviours: dict[str, dict[str, Any]] = field(default_factory=dict)
    datasets: dict[str, dict[str, Any]] = field(default_factory=dict)
    views: list[dict[str, Any]] = field(default_factory=list)
    runs: dict[str, dict[str, Any]] = field(default_factory=dict)
    reports: dict[str, dict[str, Any]] = field(default_factory=dict)
    approvals: dict[str, dict[str, Any]] = field(default_factory=dict)
    tasks: dict[str, dict[str, Any]] = field(default_factory=dict)
    definitions: dict[str, dict[str, Any]] = field(default_factory=dict)
    #: What a definition build produces, by probe id (default: a plain named document).
    built: dict[str, dict[str, Any]] = field(default_factory=dict)
    #: Label values per dataset that a view's mapping may leave unmapped (counted, never refused:
    #: ``services/probe_monitor_inputs.py:327-353``).
    labels: dict[str, list[str]] = field(default_factory=dict)
    dw_status: dict[str, dict[str, Any]] = field(default_factory=dict)
    dw_sends: dict[str, dict[str, Any]] = field(default_factory=dict)
    dw_approvals: dict[str, dict[str, Any]] = field(default_factory=dict)
    #: R3 review fix (OR3-int-2), 2026-11-16: miDataworks' detector sets (set id -> extra fields
    #: over a default with one train role), their versions' lineage (version id -> ``sources``,
    #: ``version_inputs``, ``rule_sources``) and its sources (source id -> ``token_tier``, ...).
    #: Defaults: every version reaches one public source.
    dw_sets: dict[str, dict[str, Any]] = field(default_factory=dict)
    dw_versions: dict[str, dict[str, Any]] = field(default_factory=dict)
    dw_sources: dict[str, dict[str, Any]] = field(default_factory=dict)
    #: R3 review fix (OR3-int-3): a check miDataworks' send refuses on (``prepare``: the checks
    #: run before an approval is filed; 409 ``send_refused``), or None when every check passes.
    dw_send_refused: dict[str, Any] | None = None
    sv_probes: dict[str, dict[str, Any]] = field(default_factory=dict)
    sv_events: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    models: list[dict[str, Any]] = field(default_factory=list)
    #: The Hub as miDataworks' search and preview see it: repo -> {private, gated, licence, bytes}.
    hub: dict[str, dict[str, Any]] = field(default_factory=dict)
    counter: Any = field(default_factory=lambda: itertools.count(1))

    def new_id(self, prefix: str) -> str:
        return f"{prefix}-{next(self.counter)}"

    # -- the operator's hands (tests only; miAssist never decides) ------------------------
    def approve(self, approval_id: str) -> None:
        self.approvals[approval_id]["status"] = "approved"

    def deny(self, approval_id: str, reason: str | None = "not now") -> None:
        self.approvals[approval_id].update(status="denied", reason=reason)

    def expire(self, approval_id: str) -> None:
        self.approvals[approval_id]["status"] = "expired"

    def view(self, view_id: str) -> dict[str, Any] | None:
        return next((v for v in self.views if v.get("id") == view_id), None)


def scored_rows(view: dict[str, Any]) -> int | None:
    """``services/eval_sample_size.py:scored_rows``: positive + negative, None when not recorded."""
    counts = view.get("counts") or {}
    if "positive" not in counts and "negative" not in counts:
        return None
    return int(counts.get("positive") or 0) + int(counts.get("negative") or 0)


def other_entries(world: World) -> None:
    """Entries the person never named; none may reach a result (A22)."""
    world.views.append(
        {
            "id": "other-view-1",
            "name": "other-everyday",
            "role": "everyday_text",
            "behaviour": None,
            "counts": {"positive": 0, "negative": 900},
        }
    )
    world.views.append(
        {
            "id": "other-view-2",
            "name": "other-dlp-train",
            "role": "train",
            "behaviour": "other-dlp",
            "counts": {"positive": 2, "negative": 3},
        }
    )
    world.datasets["other-ds-1"] = {"id": "other-ds-1", "name": "other-private", "status": "ready"}
    world.behaviours["other-behaviour"] = {
        "key": "other-behaviour",
        "positive_meaning": "other-meaning",
    }


# -- miWorkbench ---------------------------------------------------------------------------

VIEW = f"GET {PM}/datasets/{{dataset_id}}"
BEHAVIOUR = f"GET {PM}/behaviours/{{key}}"
VIEW_OUT_KEYS = ("id", "name", "role", "behaviour", "positive_meaning", "positive_labels_confirmed")


def _view_out(view: dict[str, Any]) -> dict[str, Any]:
    """``behaviour_catalogue.view_out``: no counts, no distribution, ``archived`` a boolean."""
    out = {k: view[k] for k in VIEW_OUT_KEYS if k in view}
    out.update(
        use=view.get("role"),
        linked_by="key",
        archived=view.get("archived_at") is not None,
        confirmed_for_this_behaviour=False,
        dataset_version=None,
    )
    return out


def _detail(world: World, key: str) -> dict[str, Any]:
    found = dict(world.behaviours[key])
    runs = found.pop("runs", [])
    found.pop("key", None)
    views = [_view_out(v) for v in world.views if v.get("behaviour") == key]
    adopted = {"prompts": [], "runs": runs, "probes": [], "views": views}
    return {
        "key": key,
        "catalogued": True,
        "current_version": 1,
        "archived": False,
        "definition": {"version": 1, **found},
        "adopted": adopted,
        "counts": {kind: len(rows) for kind, rows in adopted.items()},
    }


def _refusal(code: str, message: str) -> dict[str, Any]:
    return {"detail": {"code": code, "message": message, "next": []}}


def _approval_body(world: World, r: Recorded) -> Any:
    body = r.body or {}
    approval_id = world.new_id("mcp_ap_evalfx")
    world.approvals[approval_id] = {
        "id": approval_id,
        "status": "pending",
        "tool_name": body.get("tool_name"),
        "payload": body.get("payload"),
        "requested_by": r.headers.get("x-mistudio-agent"),
        "forecast": body.get("forecast"),
    }
    return wb("POST /api/v1/mcp/approvals", 201, world.approvals[approval_id])


def _oversized(world: World, view_ids: list[str], sample: Any) -> list[str]:
    """``eval_sample_size.too_large_to_score_whole``: empty whenever a sample is set."""
    if sample is not None:
        return []
    found = []
    for view_id in view_ids:
        view = world.view(view_id)
        rows = scored_rows(view) if view else None
        if rows is not None and rows > MAX_UNSAMPLED_EVAL_ROWS:
            found.append(view_id)
    return found


def _gpu(world: World, fake: FakeApp, method: str, template: str, action: str) -> None:
    route = f"{method} {template}"

    def handler(r: Recorded) -> Any:
        approval_id = r.headers.get("x-mistudio-approval-request")
        row = world.approvals.get(approval_id or "")
        if row is None:
            return wb(route, 403, {"detail": {"code": "approval_required", "action": action}})
        query = {k: int(v) if v.isdigit() else v for k, v in r.params.items()}
        body_param = "dataset_ids" if isinstance(r.body, list) else None
        canonical = canonical_payload(
            method, template, r.path_params, query, r.body, body_param=body_param
        )
        if row["tool_name"] != action or canonical != row["payload"]:
            detail = {"code": "mismatch", "action": action, "detail": "differs"}
            return wb(route, 422, {"detail": detail})
        if row["status"] != "approved":
            return wb(
                route, 409, {"detail": {"status": row["status"], "reason": row.get("reason")}}
            )
        row["status"] = "consumed"  # committed BEFORE the handler runs (A40)
        if action == "start_probe_training_run":
            config = (r.body or {}).get("config") or {}
            big = _oversized(
                world, r.body.get("eval_dataset_ids") or [], config.get("eval_max_rows")
            )
            if big:
                row.update(status="failed", reason="HTTPException: refused after the consume")
                return wb(route, 422, {"detail": f"{', '.join(big)} too large; set eval_max_rows"})
            run_id = world.new_id("evalfx-run")
            keep = ("model_id", "train_dataset_id", "eval_dataset_ids", "calibration_dataset_id")
            world.runs[run_id] = {
                "id": run_id,
                "status": "pending",
                "config": config,
                "environment": {},
                **{k: r.body[k] for k in keep if k in r.body},
                "behaviour": r.body.get("behaviour"),
            }
            world.behaviours[r.body.get("behaviour") or KEY].setdefault("runs", []).insert(
                0, {"id": run_id, "status": "pending"}
            )
            return wb(route, 202, {"id": run_id, "task_id": f"task-{run_id}", "status": "queued"})
        if action == "evaluate_probe_monitor":
            big = _oversized(world, list(r.body or []), r.params.get("sample_rows"))
            if big:
                row.update(status="failed", reason="HTTPException: refused after the consume")
                return wb(route, 422, {"detail": f"{', '.join(big)} too large; set sample_rows"})
        probe_id = r.path_params["probe_id"]
        if action == "build_probe_definition":
            world.definitions[probe_id] = world.built.get(probe_id, {"name": f"{KEY}-probe"})
        task_id = world.new_id("evalfx-task")
        world.tasks[task_id] = {"status": "running", "kind": action, "probe_id": probe_id}
        answer: dict[str, Any] = {"probe_id": probe_id, "task_id": task_id, "status": "queued"}
        if action == "build_probe_definition":
            answer["task_queue_id"] = world.new_id("evalfx-tq")
        return wb(route, 202, answer)

    fake.on(method, template, handler)


def _report(world: World, probe_id: str) -> Any:
    found = world.reports.get(probe_id)
    if found is None:
        return wb(f"GET {PM}/probes/{{probe_id}}", 404, {"detail": f"Probe {probe_id} not found"})
    report = dict(found)
    report.setdefault("rung_language", "")
    report.setdefault("rung_next_step", "")
    report["evaluations"] = [
        {"probe_id": probe_id, "status": "completed", **e} for e in report.get("evaluations") or []
    ]
    return wb(f"GET {PM}/probes/{{probe_id}}", 200, report)


def workbench(world: World) -> CheckedFake:
    fake = CheckedFake("miworkbench")
    fake.on(
        "GET",
        "/api/health",
        lambda r: wb(
            "GET /api/health", 200, {"status": "ok", "service": "miWorkbench Backend API"}
        ),
    )

    def behaviour(r: Recorded) -> Any:
        key = r.path_params["key"]
        if key not in world.behaviours:
            return wb(BEHAVIOUR, 404, _refusal("unknown_behaviour", f"{key!r} is not catalogued"))
        return wb(BEHAVIOUR, 200, _detail(world, key))

    def create(r: Recorded) -> Any:
        key = r.body["key"]
        route = f"POST {PM}/behaviours"
        if key in world.behaviours:
            return wb(route, 409, _refusal("behaviour_exists", f"{key!r} is already catalogued"))
        world.behaviours[key] = dict(r.body)
        return wb(route, 201, {**_detail(world, key), "warnings": []})

    def register(r: Recorded) -> Any:
        body = dict(r.body)
        schema = schema_for("miworkbench", "GET", f"{PM}/datasets/{{dataset_id}}", 200)
        kept = {k: v for k, v in body.items() if k in schema["properties"]}
        mapping = body.get("label_mapping") or {}
        # map_label: an exact key, then "*" (every remaining value; probe_monitor_inputs.py:224-230).
        values = world.labels.get(body["dataset_id"], [])
        unmapped = [] if "*" in mapping else [v for v in values if v not in mapping]
        counts = {**DEFAULT_COUNTS, "unparseable": 100 * len(unmapped), "kinds": {"plain": 1000}}
        if unmapped:
            counts["kinds"]["unmapped_label"] = 100 * len(unmapped)
        view = {"id": world.new_id("evalfx-view"), **kept, "counts": counts}
        world.views.append(view)
        return wb(f"POST {PM}/datasets", 201, view)

    def one_view(r: Recorded) -> Any:
        found = world.view(r.path_params["dataset_id"])
        if found is None:
            return wb(
                VIEW, 404, {"detail": f"Probe dataset {r.path_params['dataset_id']} not found"}
            )
        return wb(VIEW, 200, found)

    def views(r: Recorded) -> Any:
        role = r.params.get("role")
        rows = [v for v in world.views if role is None or v.get("role") == role]
        rows = [v for v in rows if v.get("archived_at") is None]
        return wb(f"GET {PM}/datasets", 200, rows)

    def nonsense(r: Recorded) -> Any:
        dataset_id = world.new_id("evalfx-ds")
        name = r.body.get("name") or f"nonsense-text-seed{r.body.get('seed', 0)}"
        view = {
            "id": world.new_id("evalfx-view"),
            "name": name,
            "dataset_id": dataset_id,
            "role": "nonsense_text",
            "behaviour": None,
            "label_mapping": {"*": "negative"},
            "counts": {"positive": 0, "negative": r.body.get("rows", 2000)},
        }
        world.views.append(view)
        answer = {
            "dataset": {"id": dataset_id, "name": name, "raw_path": "/data/evalfx"},
            "view": render("miworkbench", VIEW, 200, view),
            "manifest": {},
            "next": "evaluate_probe_monitor(probe_id, dataset_ids=[view.id])",
        }
        return wb(f"POST {PM}/nonsense-text", 201, answer)

    def dataset(r: Recorded) -> Any:
        route = "GET /api/v1/datasets/{dataset_id}"
        found = world.datasets.get(r.path_params["dataset_id"])
        if found is None:
            return wb(route, 404, {"detail": "Dataset not found"})
        return wb(route, 200, found)

    def download(r: Recorded) -> Any:
        ds_id = world.new_id("evalfx-ds")
        world.datasets[ds_id] = {"id": ds_id, "hf_repo_id": r.body["repo_id"], "status": "ready"}
        return wb("POST /api/v1/datasets/download", 202, world.datasets[ds_id])

    def run(r: Recorded) -> Any:
        route = f"GET {PM}/runs/{{run_id}}"
        found = world.runs.get(r.path_params["run_id"])
        if found is None:
            return wb(
                route, 404, {"detail": f"Probe monitor run {r.path_params['run_id']} not found"}
            )
        return wb(route, 200, found)

    def definition(r: Recorded) -> Any:
        route = f"GET {PM}/probes/{{probe_id}}/definition"
        found = world.definitions.get(r.path_params["probe_id"])
        if found is None:
            return wb(route, 409, {"detail": "no built definition; POST to this path to build one"})
        return wb(route, 200, found)

    def lookup(r: Recorded) -> Any:
        task_id = r.path_params["task_id"]
        task = world.tasks.get(task_id)
        found = (
            [{"table": "task_queue", "row_id": task_id, "status": task["status"]}] if task else []
        )
        return wb(
            "GET /api/v1/task-queue/lookup/{task_id}",
            200,
            {"task_id": task_id, "found": found, "searched": ["task_queue"]},
        )

    def approvals_list(r: Recorded) -> Any:
        status = r.params.get("status")
        rows = [a for a in world.approvals.values() if status is None or a["status"] == status]
        return wb("GET /api/v1/mcp/approvals", 200, {"approvals": rows, "total": len(rows)})

    def approval(r: Recorded) -> Any:
        route = "GET /api/v1/mcp/approvals/{request_id}"
        row = world.approvals.get(r.path_params["request_id"])
        return wb(route, 200, row) if row else wb(route, 404, {"detail": "not found"})

    fake.on("GET", f"{PM}/behaviours/{{key}}", behaviour)
    fake.on("POST", f"{PM}/behaviours", create)
    fake.on("GET", f"{PM}/datasets", views)
    fake.on("POST", f"{PM}/datasets", register)
    fake.on("GET", f"{PM}/datasets/{{dataset_id}}", one_view)
    fake.on("POST", f"{PM}/nonsense-text", nonsense)
    fake.on("GET", "/api/v1/datasets/{dataset_id}", dataset)
    fake.on(
        "GET",
        "/api/v1/datasets",
        lambda r: wb(
            "GET /api/v1/datasets",
            200,
            {"data": list(world.datasets.values()), "pagination": {"total": len(world.datasets)}},
        ),
    )
    fake.on("POST", "/api/v1/datasets/download", download)
    fake.on(
        "GET",
        "/api/v1/models",
        lambda r: wb(
            "GET /api/v1/models",
            200,
            {"data": world.models, "pagination": {"total": len(world.models)}},
        ),
    )
    fake.on(
        "GET",
        f"{PM}/datasets/{{dataset_id}}/rule-recommendation",
        lambda r: wb(
            f"GET {PM}/datasets/{{dataset_id}}/rule-recommendation",
            200,
            {
                "view_id": r.path_params["dataset_id"],
                "model_id": r.params.get("model_id"),
                "thresholds": {},
                "recorded": True,
                "shape": "local",
                "rules": ["max"],
                "rolling_windows": None,
                "reason": "positives are short spans inside longer text",
                "evidence": {},
                "cautions": [],
            },
        ),
    )

    def forecast(r: Recorded) -> Any:
        route = f"POST {PM}/runs/forecast"
        time_on = {
            "forecast": True,
            "complete": True,
            "seconds": {"low": 1200.0, "typical": 1500.0, "high": 1800.0},
            "hours": {"low": 0.33, "typical": 0.42, "high": 0.5},
            "summary": "about 25 minutes",
        }
        recommendation = {
            "view_id": (r.body or {}).get("train_dataset_id", ""),
            "recorded": True,
            "rules": ["max"],
            "reason": "positives are short spans",
            "refusal": None,
        }
        answer = {
            "checked": True,
            "fits": True,
            "needed_gib": 3.2,
            "time_forecast": render_branch(
                "miworkbench", route, 200, ("time_forecast",), 1, time_on
            ),
            "rule_recommendation": recommendation,
        }
        return wb(route, 200, answer)

    fake.on("POST", f"{PM}/runs/forecast", forecast)
    fake.on("GET", f"{PM}/runs/{{run_id}}", run)
    fake.on("GET", f"{PM}/probes/{{probe_id}}", lambda r: _report(world, r.path_params["probe_id"]))
    fake.on("GET", f"{PM}/probes/{{probe_id}}/definition", definition)
    fake.on("GET", "/api/v1/task-queue/lookup/{task_id}", lookup)
    fake.on("POST", "/api/v1/mcp/approvals", lambda r: _approval_body(world, r))
    fake.on("GET", "/api/v1/mcp/approvals", approvals_list)
    fake.on("GET", "/api/v1/mcp/approvals/{request_id}", approval)
    for (method, template), action in GPU_ROUTES.items():
        _gpu(world, fake, method, template, action)
    return fake


def render_branch(
    app: str, route: str, status: int, path: tuple[str, ...], branch: int, partial: Any
) -> Any:
    """``partial`` completed to branch ``branch`` of the ``anyOf`` at ``path`` of the answer."""
    from tests.support.response_shapes import at

    method, template = route.split(" ", 1)
    node = at(schema_for(app, method, template, status), *path)
    return fill(node["anyOf"][branch], partial)


# -- miDataworks ---------------------------------------------------------------------------

DW_STATUS = "/api/v1/behaviours/{key}/status"


def dataworks(world: World) -> CheckedFake:
    fake = CheckedFake("midataworks")
    fake.on("GET", "/api/health", lambda r: dw("GET /api/health", 200, {"status": "ok"}))

    def status(r: Recorded) -> Any:
        key = r.path_params["key"]
        found = world.dw_status.get(key)
        if found is None:
            # No 404 for an unknown key: zero counts and the first step (status_service.py).
            found = {"counts": {}}
        if found.get("rule") != "hand":
            # R3 review fix (OR3-int-3), 2026-11-16: journey, next and complete come from
            # miDataworks' own rule over the counts (tests/support/dw_journey.py), never by hand;
            # ``rule: hand`` only for a step miDataworks does not have yet (the fallback test).
            found = {**found, **dw_journey.walk(key, found.get("counts") or {})}
        found = {k: v for k, v in found.items() if k != "rule"}
        partial = {"behaviour_key": key, "shown_per_kind": 20, **found}
        if isinstance(partial.get("next"), dict):
            partial["next"] = {
                "why": "the next step",
                **partial["next"],
                "args": {"behaviour_key": key},
            }
        partial["journey"] = [
            {"also": [], "approvals": [], "done": False, "done_when": "", "tool": "", **s}
            for s in partial.get("journey") or []
        ]
        return dw(f"GET {DW_STATUS}", 200, partial)

    def send(r: Recorded) -> Any:
        if world.dw_send_refused is not None:  # send_service.prepare: the checks refuse first
            first = world.dw_send_refused
            error = {
                "code": "send_refused",
                "message": f"{first['code']} {first['title']}: {first['reason']}",
                "details": {"checks": [{"outcome": "refused", **first}]},
            }
            return dw("POST /api/v1/detector-sets/send", 409, {"error": error})
        approval_id = world.new_id("apr_evalfx")  # miDataworks' ids match ^apr_ (responses.json)
        body = {"repositories": {}, "namespace": None, "visibility": "private", **(r.body or {})}
        group = world.new_id("dsg_evalfx")
        payload = {
            "body": body,
            "send_group_id": group,
            "sends": [
                {"set_id": s, "send_id": world.new_id("dsn_evalfx"), "approval_digest": "0" * 64}
                for s in body.get("set_ids") or []
            ],
            "publish_digests": [],
            "repositories": {},
            "registrations": 0,
            "visibility": body["visibility"],
        }
        digest = hashlib.sha256(canonical_json(payload)).hexdigest()
        world.dw_approvals[approval_id] = {
            "id": approval_id,
            "status": "pending",
            "action": "hub_push",
            "requested_by": "agent:miassist",
            "payload": payload,
            "request_digest": digest,
        }
        return dw(
            "POST /api/v1/detector-sets/send",
            202,
            {
                "approval_id": approval_id,
                "status": "pending",
                "action": "hub_push",
                "request_digest": f"sha256:{digest}",
                "expires_at": "2026-11-17T00:00:00Z",
                "hint": "Waiting for the operator to approve this in miDataworks.",
                "approval": dw_approval_view(world.dw_approvals[approval_id]),
            },
        )

    def search(r: Recorded) -> Any:
        query = (r.body or {}).get("query", "")
        items = [
            {
                "repo_id": repo,
                "private": meta.get("private", False),
                "gated": meta.get("gated", False),
                "licence": meta.get("licence"),
            }
            for repo, meta in world.hub.items()
            if query in repo
        ]
        items.append({"repo_id": "other-org/other-private-set", "private": True, "gated": False})
        return dw(
            "POST /api/v1/sources/hf/search",
            200,
            {"query": query, "items": items, "total": len(items), "next_step": "preview one"},
        )

    def preview(r: Recorded) -> Any:
        repo = (r.body or {}).get("repo_id")
        meta = world.hub.get(repo, {})
        return dw(
            "POST /api/v1/sources/hf/preview",
            200,
            {
                "repo_id": repo,
                "resolved_commit": "0" * 40,
                "licence": {
                    "raw": meta.get("licence"),
                    "display": str(meta.get("licence") or "unknown"),
                    "origin": "card_data" if meta.get("licence") else "none",
                },
                "splits": [{"name": "train", "rows": None, "bytes": meta.get("bytes")}],
            },
        )

    def detector_send(r: Recorded) -> Any:
        route = "GET /api/v1/detector-sends/{send_id}"
        found = world.dw_sends.get(r.path_params["send_id"])
        if found is None:
            error = {"code": "send_not_found", "message": "no such send", "details": {}}
            return dw(route, 404, {"error": error})
        # the two digests are sha256 hex (``^[0-9a-f]{64}$``), never ``example``'s placeholder
        digests = {"snapshot_sha256": "0" * 64, "approval_digest": "0" * 64}
        return dw(route, 200, {"id": r.path_params["send_id"], **digests, **found})

    def approval(r: Recorded) -> Any:
        route = "GET /api/v1/approvals/{approval_id}"
        found = world.dw_approvals.get(r.path_params["approval_id"])
        if found is None:
            # miDataworks' NotFoundError is NOT_FOUND (core/errors.py:50; approval_service.py:94)
            error = {"code": "NOT_FOUND", "message": "No approval.", "details": {}}
            return dw(route, 404, {"error": error})
        return dw(route, 200, {**found, "approval": dw_approval_view(found)})

    def approvals(r: Recorded) -> Any:
        status = r.params.get("status")
        rows = [
            {**a, "approval": dw_approval_view(a)}
            for a in world.dw_approvals.values()
            if status in (None, a["status"])
        ]
        return dw("GET /api/v1/approvals", 200, {"approvals": rows, "total": len(rows)})

    fake.on("POST", "/api/v1/sources/hf/search", search)
    fake.on("POST", "/api/v1/sources/hf/preview", preview)
    fake.on("GET", DW_STATUS, status)
    fake.on(
        "GET",
        "/api/v1/behaviours/{key}/resolve",
        lambda r: dw(
            "GET /api/v1/behaviours/{key}/resolve",
            200,
            {
                "key": r.path_params["key"],
                "verified": False,
                "reason": "not verified against a catalogue",
                "detail": "miWorkbench is not configured on this miDataworks",
                "record": {
                    "key": r.path_params["key"],
                    "verified": False,
                    "source": "supplied",
                    "read_at": "2026-11-16T00:00:00Z",
                },
            },
        ),
    )

    def detector_set(r: Recorded) -> Any:
        set_id = r.path_params["set_id"]
        listed = (world.dw_status.get(KEY) or {}).get("objects", {}).get("detector_sets") or []
        row = next((s for s in listed if s.get("id") == set_id), None)
        if row is None and set_id not in world.dw_sets:
            error = {"code": "NOT_FOUND", "message": "no such set", "details": {}}
            return dw("GET /api/v1/detector-sets/{set_id}", 404, {"error": error})
        role = {
            "id": f"{set_id}-train",
            "role": "train",
            "version_id": f"evalfx-dwver-{set_id}",
            "version_number": 1,
            "version_state": "completed",
            "dataset_id": "evalfx-dwds-1",
            "dataset_name": "carriers",
        }
        body = {
            "id": set_id,
            "name": (row or {}).get("name", set_id),
            "archived": bool((row or {}).get("archived")),
            "roles": [role],
            "borrowed_roles": [],
            "profiles": {},
            "sends": [],
            **world.dw_sets.get(set_id, {}),
        }
        return dw("GET /api/v1/detector-sets/{set_id}", 200, body)

    def lineage_of(version_id: str) -> dict[str, Any]:
        return {
            "sources": ["evalfx-dwsrc-public"],
            "version_inputs": [],
            "rule_sources": [],
            **world.dw_versions.get(version_id, {}),
        }

    def manifest(r: Recorded) -> Any:
        """``build_manifest``: ``sources`` transitive through input versions AND rule_source
        ancestors (``version_finalize.transitive_sources``); ``inputs`` the request's only."""
        version_id = r.path_params["version_id"]
        own = lineage_of(version_id)
        reached: list[str] = []
        todo, seen = [version_id], set()
        while todo:
            v = todo.pop()
            if v in seen:
                continue
            seen.add(v)
            here = lineage_of(v)
            reached += [s for s in here["sources"] if s not in reached]
            todo += here["version_inputs"] + here["rule_sources"]
        inputs = [{"kind": "source", "source_id": s} for s in own["sources"]] + [
            {"kind": "version", "version_id": v} for v in own["version_inputs"]
        ]
        body = {
            "format": "dw.manifest/v1",
            "version_id": version_id,
            "number": 1,
            "inputs": inputs,
            "sources": [{"source_id": s, "kind": "hf"} for s in sorted(reached)],
        }
        return dw("GET /api/v1/versions/{version_id}/manifest", 200, body)

    def lineage(r: Recorded) -> Any:
        version_id = r.path_params["version_id"]
        own = lineage_of(version_id)
        body = {
            "version_id": version_id,
            "inputs": [{"kind": "source", "source_id": s} for s in own["sources"]]
            + [{"kind": "version", "version_id": v} for v in own["version_inputs"]],
            "label_balancing": [],
            "parent_version_id": None,
            "children": [],
            "rule_sources": [{"version_id": v, "number": 1} for v in own["rule_sources"]],
            "steps": [],
        }
        return dw("GET /api/v1/versions/{version_id}/lineage", 200, body)

    def source(r: Recorded) -> Any:
        source_id = r.path_params["source_id"]
        extra = {"token_tier": "none", "gated": None, **world.dw_sources.get(source_id, {})}
        return dw(
            "GET /api/v1/sources/{source_id}",
            200,
            {"id": source_id, "kind": "hf", "state": "ready", **extra},
        )

    fake.on("POST", "/api/v1/detector-sets/send", send)
    fake.on("GET", "/api/v1/detector-sets/{set_id}", detector_set)
    fake.on("GET", "/api/v1/versions/{version_id}/manifest", manifest)
    fake.on("GET", "/api/v1/versions/{version_id}/lineage", lineage)
    fake.on("GET", "/api/v1/sources/{source_id}", source)
    fake.on("GET", "/api/v1/detector-sends/{send_id}", detector_send)
    fake.on("GET", "/api/v1/approvals/{approval_id}", approval)
    fake.on("GET", "/api/v1/approvals", approvals)
    return fake


# -- miServer ------------------------------------------------------------------------------


def _envelope(data: Any) -> dict[str, Any]:
    return {"success": True, "data": data, "error": None}


def server(world: World) -> CheckedFake:
    fake = CheckedFake("miserver")
    fake.on("GET", "/api/health", lambda r: sv("GET /api/health", 200, {"status": "healthy"}))

    def status(r: Recorded) -> Any:
        armed = [
            {"id": p["id"], "name": p.get("name", ""), "paused_reason": p.get("paused_reason")}
            for p in world.sv_probes.values()
            if p.get("armed")
        ]
        data = {
            "armed": armed,
            "armed_count": len(armed),
            "catalogue": {"imported": len(world.sv_probes), "behaviours": 0},
            "imported_count": len(world.sv_probes),
        }
        return sv("GET /api/probes/status", 200, _envelope(data))

    def events(r: Recorded) -> Any:
        wanted = {"fired": True, "not_fired": False, "not_scored": None}.get(
            r.params.get("verdict", ""), "?"
        )
        rows = [
            {**e, "verdict": {"fired": True, "not_fired": False}.get(e["verdict"])}
            for e in world.sv_events.get(r.params.get("probe_id", ""), [])
        ]
        rows = [e for e in rows if e["verdict"] == wanted]
        limit = int(r.params.get("limit", 100))
        meta = {"next": "c2" if len(rows) > limit else None, "limit": limit}
        return sv("GET /api/probes/events", 200, {**_envelope(rows[:limit]), "meta": meta})

    def import_probe(r: Recorded) -> Any:
        route = "POST /api/probes/import"
        name = (r.body or {}).get("name", "probe")
        if any(p["name"] == name for p in world.sv_probes.values()):
            # probe_service._dedupe_name: on_conflict=fail -> ValidationError (422).
            message = f"A probe named '{name}' already exists"
            error = {
                "code": "VALIDATION_ERROR",
                "message": message,
                "details": {
                    "user_message": message,
                    "technical_message": message,
                    "name": name,
                    "code": "NAME_CONFLICT",
                },
            }
            return sv(route, 422, {"success": False, "data": None, "error": error})
        probe_id = world.new_id("evalfx-svprobe")
        world.sv_probes[probe_id] = {"id": probe_id, "name": name, "armed": False}
        return sv(route, 200, _envelope({"id": probe_id, "name": name, "armed": False}))

    def probes(r: Recorded) -> Any:
        rows = [
            {
                "id": p["id"],
                "name": p["name"],
                "hf_id": p.get("hf_id") or "",
                "armed": bool(p.get("armed")),
            }
            for p in world.sv_probes.values()
        ]
        return sv("GET /api/probes", 200, {**_envelope(rows), "meta": {"next": None, "limit": 100}})

    fake.on("GET", "/api/probes", probes)
    fake.on("GET", "/api/probes/status", status)
    fake.on("GET", "/api/probes/events", events)
    fake.on("POST", "/api/probes/import", import_probe)
    fake.on(
        "GET",
        "/api/models",
        lambda r: sv("GET /api/models", 200, _envelope([{"id": 1, "name": "evalfx-model"}])),
    )
    fake.on(
        "GET",
        "/api/approvals",
        lambda r: sv(
            "GET /api/approvals", 200, _envelope({"approvals": [], "count": 0, "pending": 0})
        ),
    )
    return fake


def fakes_for(world: World) -> dict[str, FakeApp]:
    return {
        "miworkbench": workbench(world),
        "midataworks": dataworks(world),
        "miserver": server(world),
        "miforge": FakeApp("miforge"),
    }
