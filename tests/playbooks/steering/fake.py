"""Stateful fakes of miWorkbench's steering routes and miServer's serving routes (005 tests).

Every answer is BUILT from the apps' own response shapes (``tests/fixtures/openapi/responses.json`` and
the OpenAPI snapshots beside it, at the commits they record) and checked against them by ``ShapedFakeApp``
(R1 review fixes OR1-pb-2 to OR1-pb-5, 2026-11-16): a task's ``status`` is a SteeringTaskStatus
object; a sweep's ``result`` is a StrengthSweepResponse and a combined one a CombinedSteeringResponse
(``combined_output``, ``features_applied``); miServer's import answers a ClusterImportResult, its
clusters carry ``(feature_idx, label, strength)`` triples, its detailed health is top-level
``model_name`` / ``sae_ids`` / ``active_profile {id, name}``, and its models have integer ids.
Fixture ids use the ``evalfx-`` prefix (A22).
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from typing import Any

import httpx

from miassist.adapters.steering import GPU_ROUTES, STEERING_ROUTES
from tests.support.fake_apps import FakeApp, Recorded
from tests.support.shapes import fill, instance, part, shaped_fakes

FLUENT = "the weather today is bright and warm with a light breeze over the quiet harbour town"
COLLAPSED = "sea sea sea sea sea sea sea sea sea sea"
WB, SV = "miworkbench", "miserver"
HF_ID = "evalfx-org/evalfx-model"
RESULT = "GET /api/v1/steering/async/result/{task_id}"


@dataclass
class Steering:
    sweep_texts: list[str] = field(
        default_factory=lambda: [FLUENT, FLUENT, COLLAPSED, COLLAPSED, COLLAPSED]
    )
    #: The task's statuses, one per read (the last repeats): SteeringTaskStatus.status values.
    task_states: list[str] = field(default_factory=lambda: ["success"])
    task_error: str = "CUDA out of memory"
    max_activation: float = 10.0
    combined_text: str = FLUENT
    #: Members the combined task reports it applied (None: the ones it was sent).
    applied_override: list[dict[str, Any]] | None = None
    approvals: list[dict[str, Any]] = field(default_factory=list)
    profiles: list[dict[str, Any]] = field(default_factory=list)
    clusters: list[dict[str, Any]] = field(default_factory=list)
    sv_approvals: list[dict[str, Any]] = field(default_factory=list)
    #: miServer's downloaded model and whether it is resident; ``None``: none downloaded.
    model_status: str | None = "loaded"
    #: Other downloaded models listed BEFORE the cluster's (R3 review fix OR3-int-5, SW09: a decoy).
    other_models: list[dict[str, Any]] = field(default_factory=list)
    attached_sae: str | None = "evalfx-sae-1"
    #: The name of the active cluster.
    active: str | None = None
    #: An export whose members map to nothing in miServer (the trial must refuse).
    export_members: list[dict[str, Any]] | None = None
    #: ClusterImportItem.status miServer answers (imported, imported_unbound, blocked, error).
    import_status: str = "imported"
    tasks: dict[str, dict[str, Any]] = field(default_factory=dict)
    ids: Any = field(default_factory=lambda: itertools.count(1))

    def new(self, prefix: str) -> str:
        return f"evalfx-{prefix}-{next(self.ids)}"

    def install(self, wb: FakeApp, sv: FakeApp) -> None:
        self.wb, self.sv = wb, sv
        ext = part(WB, "GET /api/v1/extractions", 200, "data", "[]")
        wb.on(
            "GET",
            "/api/v1/extractions",
            lambda r: instance(
                WB,
                "GET /api/v1/extractions",
                200,
                data=[
                    fill(
                        ext,
                        id="evalfx-ext-1",
                        external_sae_id="evalfx-sae-1",
                        layer_index=6,
                        status="completed",
                        model_name="evalfx-model",
                        created_at="2026-11-01T00:00:00Z",
                    )
                ],
                meta={},
            ),
        )
        wb.on(
            "GET",
            "/api/v1/extractions/{extraction_id}/features",
            lambda r: instance(
                WB,
                "GET /api/v1/extractions/{extraction_id}/features",
                200,
                features=[self.feature("evalfx-feat-1", 42, listed=True)],
                total=1,
                limit=50,
                offset=0,
            ),
        )
        wb.on(
            "GET",
            "/api/v1/features/{feature_id}",
            lambda r: self.feature(
                r.path_params["feature_id"], 42 if r.path_params["feature_id"].endswith("1") else 7
            ),
        )
        wb.on(
            "GET",
            "/api/v1/saes/{sae_id}",
            lambda r: instance(
                WB,
                "GET /api/v1/saes/{sae_id}",
                200,
                id="evalfx-sae-1",
                name="evalfx sae",
                model_id="evalfx-model",
                layer=6,
                status="ready",
                source="huggingface",
                format="community_standard",
            ),
        )
        wb.on("POST", "/api/v1/mcp/approvals", self.file)
        wb.on(
            "GET",
            "/api/v1/mcp/approvals",
            lambda r: (
                lambda found: instance(
                    WB, "GET /api/v1/mcp/approvals", 200, approvals=found, total=len(found)
                )
            )([a for a in self.approvals if a["status"] == r.params.get("status", a["status"])]),
        )
        wb.on(
            "GET",
            "/api/v1/mcp/approvals/{request_id}",
            lambda r: next(
                (a for a in self.approvals if a["id"] == r.path_params["request_id"]), None
            )
            or wb.error(404, "not_found"),
        )
        wb.on("POST", "/api/v1/steering/async/sweep", self.run)
        wb.on("POST", "/api/v1/steering/async/combined", self.run)
        wb.on("GET", RESULT.split(" ", 1)[1], self.result)
        wb.on(
            "GET",
            "/api/v1/cluster-profiles",
            lambda r: instance(
                WB,
                "GET /api/v1/cluster-profiles",
                200,
                data=self.profiles,
                total=len(self.profiles),
            ),
        )
        wb.on("POST", "/api/v1/cluster-profiles", self.save)
        wb.on("GET", "/api/v1/cluster-profiles/{profile_id}/export", self.export)
        sv.on("GET", "/api/clusters", self.list_clusters)
        sv.on("POST", "/api/clusters/import", self.import_cluster)
        sv.on("GET", "/api/health/detailed", self.health)
        sv.on("GET", "/api/models", self.models)
        sv.on("POST", "/api/models/{model_id}/load", self.load)
        sv.on(
            "GET",
            "/api/approvals",
            lambda r: (
                lambda found: instance(
                    SV,
                    "GET /api/approvals",
                    200,
                    success=True,
                    data={"approvals": found, "count": len(found), "pending": len(found)},
                )
            )([a for a in self.sv_approvals if a["status"] == r.params.get("status", a["status"])]),
        )
        sv.on(
            "GET",
            "/api/approvals/{approval_id}",
            lambda r: instance(
                SV,
                "GET /api/approvals/{approval_id}",
                200,
                success=True,
                data=next(
                    a for a in self.sv_approvals if a["approval_id"] == r.path_params["approval_id"]
                ),
            ),
        )
        sv.on("POST", "/v1/chat/completions", self.chat)

    # -- miWorkbench -------------------------------------------------------------------------------

    def feature(self, fid: str, index: int, *, listed: bool = False) -> dict[str, Any]:
        fields = {
            "id": fid,
            "extraction_job_id": "evalfx-ext-1",
            "neuron_index": index,
            "name": "weather words",
            "activation_frequency": 0.01,
            "max_activation": self.max_activation,
            "interpretability_score": 0.99,
            "label_source": "auto",
        }
        if listed:
            return fill(
                part(WB, "GET /api/v1/extractions/{extraction_id}/features", 200, "features", "[]"),
                **fields,
            )
        return instance(WB, "GET /api/v1/features/{feature_id}", 200, **fields)

    def file(self, r: Recorded) -> Any:
        a = instance(
            WB,
            "POST /api/v1/mcp/approvals",
            201,
            id=self.new("req"),
            tool_name=r.body["tool_name"],
            payload=r.body["payload"],
            status="pending",
            requested_by="miassist",
            created_at=f"2026-11-16T00:00:{len(self.approvals):02d}Z",
        )
        self.approvals.append(a)
        return httpx.Response(201, json=a)

    def approve(self, status: str = "approved") -> None:
        self.approvals[-1]["status"] = status

    def run(self, r: Recorded) -> Any:
        task = self.new("task")
        sweep = r.path.endswith("sweep")
        self.tasks[task] = {"sweep": sweep, "body": r.body or {}, "reads": 0}
        for a in self.approvals:
            if a["id"] == r.headers.get("x-mistudio-approval-request"):
                a["status"] = "consumed"
        return instance(
            WB,
            "POST /api/v1/steering/async/sweep",
            200,
            task_id=task,
            task_type="sweep" if sweep else "combined",
            status="pending",
            websocket_channel=f"steering/{task}",
            message="queued",
            submitted_at="2026-11-16T00:00:00Z",
        )

    def result(self, r: Recorded) -> Any:
        task_id = r.path_params["task_id"]
        task = self.tasks[task_id]
        state = self.task_states[min(task["reads"], len(self.task_states) - 1)]
        task["reads"] += 1
        status = fill(
            part(WB, RESULT, 200, "status"),
            task_id=task_id,
            status=state,
            error=self.task_error if state == "failure" else None,
        )
        body = task["body"]
        result: dict[str, Any] | None = None
        if state == "success" and task["sweep"]:
            strengths = body.get("strength_values") or [1.0]
            result = {
                "sweep_id": "evalfx-sweep",
                "sae_id": body.get("sae_id"),
                "model_id": "evalfx-model",
                "prompt": body.get("prompt"),
                "feature_idx": body.get("feature_idx"),
                "layer": body.get("layer"),
                "unsteered": {"text": FLUENT},
                "results": [
                    {"strength": x, "text": t}
                    for x, t in zip(strengths, self.sweep_texts, strict=False)
                ],
                "total_time_ms": 10,
                "created_at": "2026-11-16T00:00:00Z",
            }
        elif state == "success":
            applied = self.applied_override
            if applied is None:
                applied = [
                    {
                        "feature_idx": f["feature_idx"],
                        "layer": f["layer"],
                        "strength": f["strength"],
                    }
                    for f in body.get("selected_features") or []
                ]
            result = {
                "combined_id": "evalfx-comb",
                "sae_id": body.get("sae_id"),
                "model_id": "evalfx-model",
                "prompt": body.get("prompt"),
                "combined_output": self.combined_text,
                "features_applied": applied,
                "baseline_output": FLUENT,
                "total_steering_strength": sum(abs(f["strength"]) for f in applied),
                "total_time_ms": 10,
                "created_at": "2026-11-16T00:00:00Z",
            }
        return instance(WB, RESULT, 200, task_id=task_id, status=status, result=result)

    def save(self, r: Recorded) -> Any:
        member = part(WB, "POST /api/v1/cluster-profiles", 201, "members", "[]")
        names = set(member["properties"])
        p = instance(
            WB,
            "POST /api/v1/cluster-profiles",
            201,
            id=self.new("prof"),
            name=r.body["name"],
            sae_id=r.body.get("sae_id"),
            model_id=r.body.get("model_id"),
            members=[
                fill(member, **{k: v for k, v in m.items() if k in names})
                for m in r.body["members"]
            ],
        )
        self.profiles.append(p)
        return httpx.Response(201, json=p)

    def export(self, r: Recorded) -> Any:
        for p in self.profiles:
            if p["id"] == r.path_params["profile_id"]:
                members = self.export_members
                if members is None:
                    members = [
                        {"feature_idx": m["feature_idx"], "strength": m["strength"]}
                        for m in p["members"]
                    ]
                return instance(
                    WB,
                    "GET /api/v1/cluster-profiles/{profile_id}/export",
                    200,
                    kind="mistudio.cluster-definition",
                    name=p["name"],
                    model={"hf_id": HF_ID},
                    sae={"mistudio_sae_id": p["sae_id"], "layer": 6},
                    members=members,
                )
        return self.wb.error(404, "not_found")

    # -- miServer ----------------------------------------------------------------------------------

    def cluster(self, doc: dict[str, Any], **extra: Any) -> dict[str, Any]:
        """A ClusterSummary as miServer lists it after an import (cluster_service.py:97-108)."""
        members = [[m["feature_idx"], m.get("label"), m["strength"]] for m in doc["members"]]
        return fill(
            part(SV, "GET /api/clusters", 200, "data", "clusters", "[]"),
            id=extra.pop("id", None) or self.new("prof"),
            name=doc["name"],
            model_id=(doc.get("model") or {}).get("hf_id"),
            sae_id=(doc.get("sae") or {}).get("mistudio_sae_id"),
            is_active=doc["name"] == self.active,
            intensity=1.0,
            sensing_enabled=False,
            member_count=len(members),
            members=members,
            created_at="2026-11-16T00:00:00Z",
            updated_at="2026-11-16T00:00:00Z",
            **extra,
        )

    def list_clusters(self, r: Recorded) -> Any:
        for c in self.clusters:
            c["is_active"] = c["name"] == self.active
        active = next((c["id"] for c in self.clusters if c["is_active"]), None)
        return instance(
            SV,
            "GET /api/clusters",
            200,
            success=True,
            data={"active_cluster_id": active, "clusters": self.clusters},
        )

    def import_cluster(self, r: Recorded) -> Any:
        doc = r.body or {}
        if any(c["name"] == doc.get("name") for c in self.clusters):
            return httpx.Response(
                422,
                json={
                    "success": False,
                    "data": None,
                    "error": {
                        "code": "VALIDATION_ERROR",
                        "message": f"A profile named '{doc.get('name')}' already exists",
                        "details": {"name": doc.get("name")},
                    },
                },
            )
        if self.import_status in ("blocked", "error"):
            item = {"name": doc.get("name"), "status": self.import_status, "error": "SAE unbound"}
            return instance(
                SV,
                "POST /api/clusters/import",
                200,
                success=True,
                data={"results": [item], "imported": 0, "blocked": 1, "errors": 0},
            )
        c = self.cluster(doc)
        self.clusters.append(c)
        item = {"name": c["name"], "status": self.import_status, "profile_id": c["id"]}
        return instance(
            SV,
            "POST /api/clusters/import",
            200,
            success=True,
            data={"results": [item], "imported": 1, "blocked": 0, "errors": 0},
        )

    def health(self, r: Recorded) -> Any:
        active = next((c for c in self.clusters if c["name"] == self.active), None)
        return instance(
            SV,
            "GET /api/health/detailed",
            200,
            status="healthy",
            model_loaded=self.model_status == "loaded",
            model_name="evalfx-model" if self.model_status == "loaded" else None,
            sae_attached=self.attached_sae is not None,
            sae_id=self.attached_sae,
            sae_ids=[self.attached_sae] if self.attached_sae else [],
            sae_count=1 if self.attached_sae else 0,
            active_profile=(
                {"id": active["id"], "name": active["name"], "source_kind": "cluster"}
                if active
                else None
            ),
        )

    def models(self, r: Recorded) -> Any:
        rows = [
            fill(
                part(SV, "GET /api/models", 200, "data", "[]"),
                source="huggingface",
                quantization="FP16",
                created_at="2026-11-01T00:00:00Z",
                updated_at="2026-11-01T00:00:00Z",
                **other,
            )
            for other in self.other_models
        ]
        if self.model_status is not None:
            rows.append(
                fill(
                    part(SV, "GET /api/models", 200, "data", "[]"),
                    id=3,
                    name="evalfx-model",
                    repo_id=HF_ID,
                    status=self.model_status,
                    source="huggingface",
                    quantization="FP16",
                    created_at="2026-11-01T00:00:00Z",
                    updated_at="2026-11-01T00:00:00Z",
                )
            )
        return instance(SV, "GET /api/models", 200, success=True, data=rows)

    def load(self, r: Recorded) -> Any:
        a = {
            "approval_id": self.new("apv"),
            "action": "model_load",
            "action_label": "Load a model",
            "settings_change": False,
            "batch_kind": None,
            "status": "pending",
            "summary": {},
            "payload": {"model_id": int(r.path_params["model_id"]), "request": None},
            "request_digest": "sha256:evalfx",
            "requested_by": "agent:miassist",
            "decided_by": None,
            "reason": None,
            "result": None,
            "error": None,
            "created_at": "2026-11-16T00:00:00+00:00",
            "decided_at": None,
            "expires_at": "2026-11-17T00:00:00+00:00",
            "batch_id": None,
        }
        self.sv_approvals.append(a)
        pending = {
            k: a[k]
            for k in ("approval_id", "status", "action", "summary", "request_digest", "expires_at")
        }
        return httpx.Response(
            202,
            json={
                "success": True,
                "data": {
                    **pending,
                    "hint": "Waiting for the operator to approve this in miServer.",
                },
                "error": None,
            },
            headers={"X-miLLM-Approval": "pending"},
        )

    def chat(self, r: Recorded) -> Any:
        choice = fill(
            part(SV, "POST /v1/chat/completions", 200, "choices", "[]"),
            index=0,
            finish_reason="length",
            message={"role": "assistant", "content": FLUENT},
        )
        return instance(
            SV,
            "POST /v1/chat/completions",
            200,
            id="evalfx-chat",
            created=0,
            model=(r.body or {}).get("model") or "evalfx-model",
            choices=[choice],
            usage={"prompt_tokens": 3, "completion_tokens": 20, "total_tokens": 23},
        )


def fakes_with(s: Steering) -> dict[str, FakeApp]:
    fakes = shaped_fakes(("miworkbench", "miserver"))
    s.install(fakes["miworkbench"], fakes["miserver"])
    return fakes


ALL_ROUTES = (*STEERING_ROUTES, *GPU_ROUTES)
