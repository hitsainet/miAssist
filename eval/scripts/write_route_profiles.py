"""Write eval/route_profiles/<app>.yaml (FTASKS 3.3; FTDD §4.3; FR-002.14b-c; OVN-miassist-eval-7).

The hand-chosen parts are the dictionaries below (agent headers from Core's HEADERS, poll states
read from each app's models and cited, the creates routes' rule, miWorkbench's partial-arm overlay).
The list entries are derived from the reference OpenAPI so none is missed: every GET without a path
parameter gets a ``list`` entry (Core's filter walks any depth; ``items`` names where the array is,
for the count rewrite). A GET with a path parameter whose answer holds an array of objects gets a
real ``list`` entry too (R1 review fix OR1-002-2, 2026-11-16, OVN-miassist-eval-20 reversing OVN-7:
items under a fixture parent are not necessarily fixture items, e.g. related features). Re-run after
a reference refresh; ``tests/unit/test_list_routes_covered.py`` fails on an uncovered route.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import yaml

EVAL = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(EVAL), str(EVAL.parent)]

from miassist_eval import allowed, openapi_ref  # noqa: E402

# 001's HEADERS (src/miassist/adapters/headers.py), restated per profile and pinned against Core's
# constant by tests/unit/test_agent_headers.py (R1M-15).
AGENT_HEADERS = {
    "miworkbench": {"name": "X-MiStudio-Agent", "value": "miassist"},
    "miserver": {"name": "X-miLLM-Agent", "value": "agent:miassist"},
    "midataworks": {"name": "X-Dataworks-Agent", "value": "agent:miassist"},
    "miforge": {"name": "X-Miforge-Agent", "value": "agent:miassist"},
}
# A6's seven states, in each app's own names (FTASKS 3.3 citations in the comments).
POLLS: dict[str, list[dict[str, Any]]] = {
    "miworkbench": [
        # models/agent_approval.py:21-30 (pending, approved, denied, expired, consumed)
        {
            "method": "GET",
            "route": "/api/v1/mcp/approvals/{request_id}",
            "poll_of": "approval",
            "state_field": "status",
            "open_states": ["pending"],
            "closed_states": ["approved", "denied", "expired"],
            "run_states": [],
            "done_states": ["consumed"],
        },
        # schemas/probe_monitor.py:640; services/probe_monitor_run.py:900
        {
            "method": "GET",
            "route": "/api/v1/probe-monitors/runs/{run_id}",
            "poll_of": "run",
            "state_field": "status",
            "open_states": ["queued", "running", "pending"],
            "closed_states": ["completed", "failed", "cancelled", "refused"],
        },
        # schemas/steering.py:414-424
        {
            "method": "GET",
            "route": "/api/v1/steering/async/result/{task_id}",
            "poll_of": "task",
            "state_field": "status",
            "open_states": ["pending", "started", "progress"],
            "closed_states": ["success", "failure", "revoked"],
        },
    ],
    "midataworks": [
        # models/approval.py:18-25
        {
            "method": "GET",
            "route": "/api/v1/approvals/{approval_id}",
            "poll_of": "approval",
            "state_field": "status",
            "open_states": ["pending"],
            "closed_states": ["rejected", "expired"],
            "run_states": ["executing"],
            "done_states": ["executed", "failed"],
        },
        # models/job.py:18-26
        {
            "method": "GET",
            "route": "/api/v1/jobs/{job_id}",
            "poll_of": "job",
            "state_field": "status",
            "open_states": ["queued", "running", "cancelling"],
            "closed_states": ["cancelled", "completed", "failed"],
        },
        # models/publish.py:50-54
        {
            "method": "GET",
            "route": "/api/v1/publish-check-runs/{check_run_id}",
            "poll_of": "job",
            "state_field": "status",
            "open_states": ["queued"],
            "closed_states": ["completed", "failed", "cancelled"],
        },
    ],
    "miforge": [
        # models/approval.py:51-57
        {
            "method": "GET",
            "route": "/api/v1/approvals/{approval_id}",
            "poll_of": "approval",
            "state_field": "status",
            "open_states": ["pending"],
            "closed_states": ["rejected", "expired"],
            "run_states": ["executing"],
            "done_states": ["executed", "failed"],
        },
    ],
    "miserver": [
        # services/approval_service.py:120-224 (the same seven-state vocabulary, under ApiResponse.data)
        {
            "method": "GET",
            "route": "/api/approvals/{approval_id}",
            "poll_of": "approval",
            "state_field": "data.status",
            "open_states": ["pending"],
            "closed_states": ["rejected", "expired"],
            "run_states": ["executing"],
            "done_states": ["executed", "failed"],
        },
    ],
}
SPECIAL: dict[str, list[dict[str, Any]]] = {
    "midataworks": [
        # A23: only public, ungated Hugging Face results, and only those Core's filter keeps.
        {
            "method": "POST",
            "route": "/api/v1/sources/hf/search",
            "list": {"items": "*", "id": "id", "keep_if": {"private": False, "gated": False}},
        },
    ],
}
# A41 (R3A-6): the partial arms, keyed by route, read where and as the route reads them.
GPU_ARMS = {
    "POST /api/v1/probe-monitors/probes/{probe_id}/recalibrate": {
        # probe_monitors.py:1773-1779: a FastAPI query boolean, default False
        "from": "query.recut_windows",
        "parse": "fastapi_bool",
        "armed_unless": False,
    },
    "POST /api/v1/trainings/{training_id}/control": {
        # schemas/training.py:713-719: a Literal; only resume starts GPU work
        "from": "body.action",
        "parse": "literal",
        "armed_unless_in": ["pause", "stop", "stop_and_finalize"],
    },
}
COUNT_FIELDS = ("total", "count", "total_count")


def _schema_props(route: Any, doc: Any) -> dict[str, Any]:
    comps = doc.openapi.get("components", {}).get("schemas", {})
    for status, entry in route.op.get("responses", {}).items():
        if status.startswith("2"):
            schema = ((entry.get("content") or {}).get("application/json") or {}).get(
                "schema"
            ) or {}
            if isinstance(schema.get("$ref"), str):
                schema = comps.get(schema["$ref"].rsplit("/", 1)[1], {})
            return dict(schema.get("properties") or {})
    return {}


def _request_props(route: Any, doc: Any) -> dict[str, Any]:
    comps = doc.openapi.get("components", {}).get("schemas", {})
    rb = ((route.op.get("requestBody") or {}).get("content") or {}).get("application/json") or {}
    schema = rb.get("schema") or {}
    if isinstance(schema.get("$ref"), str):
        schema = comps.get(schema["$ref"].rsplit("/", 1)[1], {})
    return dict(schema.get("properties") or {})


def profile(app: str) -> dict[str, Any]:
    doc = openapi_ref.load(app)
    comps = doc.openapi.get("components", {}).get("schemas", {})
    entries: dict[tuple[str, str], dict[str, Any]] = {}
    for route in doc.routes:
        key = (route.method, route.template)
        has_params = "{" in route.template
        if route.method == "GET":
            schema = None
            for status, e in route.op.get("responses", {}).items():
                if status.startswith("2"):
                    schema = ((e.get("content") or {}).get("application/json") or {}).get("schema")
                    break
            where = allowed.schema_object_array(schema, comps)
            if not has_params or where is not None:
                props = _schema_props(route, doc)
                spec: dict[str, Any] = {"items": where if where else "*", "id": "id"}
                counts = [c for c in COUNT_FIELDS if c in props]
                if counts:
                    spec["counts"] = counts
                entries[key] = {"method": route.method, "route": route.template, "list": spec}
        elif route.method == "POST" and not has_params and doc.route("GET", route.template):
            # A collection create only (the same template lists): a POST that merely tests or
            # previews never adds a name to the allowed set (narrowing; OVN-miassist-eval-7).
            if {"name", "key"} & set(_request_props(route, doc)):
                entries[key] = {"method": route.method, "route": route.template, "creates": True}
    for extra in POLLS.get(app, []) + SPECIAL.get(app, []):
        key = (extra["method"], extra["route"])
        entries[key] = {**entries.get(key, {}), **extra}
    out: dict[str, Any] = {
        "schema": "miassist.eval-route-profile/v1",
        "app": app,
        "agent_header": AGENT_HEADERS[app],
        "default_match": ["query", "body"],
        "routes": [entries[k] for k in sorted(entries)],
    }
    if app == "miworkbench":
        out["gpu_arms"] = GPU_ARMS
    return out


def main() -> int:
    for app in openapi_ref.APPS:
        data = profile(app)
        head = (
            f"# Route profile for {app} (FTDD §4.3), written by eval/scripts/"
            "write_route_profiles.py from\n# the reference OpenAPI; edit the script, not "
            "this file. No GPU route is listed here (R2M-14):\n# the guarded list is derived "
            "from the vendored payload vectors at suite start.\n"
        )
        text = head + yaml.safe_dump(data, sort_keys=False, width=110)
        (EVAL / "route_profiles" / f"{app}.yaml").write_text(text)
        print(app, len(data["routes"]), "routes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
