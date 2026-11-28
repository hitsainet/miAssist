"""A stateful fake miDataworks for the dataset playbook (004 tests).

Every answer is BUILT from miDataworks' own response shapes (``tests/fixtures/openapi/responses.json`` and the
OpenAPI snapshot, both at 58087b1, each code-derived shape with its cite) and every answer is checked
against them by ``ShapedFakeApp`` (R1 review fix OR1-pb-1, 2026-11-16): a field miDataworks never
sends fails the test. Statuses are miDataworks' enums (jobs ``completed``, builds ``completed``,
versions ``completed``). Recorded cassettes are the operator's step (A22; OPERATOR.md); these
fixtures use only ``evalfx-`` ids. Every request is recorded by ``FakeApp`` (the request log), which
also refuses a request without miDataworks' agent header.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from typing import Any

import httpx

from tests.support.fake_apps import FakeApp, Recorded
from tests.support.shapes import fill, instance, part, shaped_fakes

PUBLIC = "evalfx-org/support-chats"
PRIVATE = "evalfx-org/private-chats"
GATED = "evalfx-org/gated-chats"
APP = "midataworks"


def hub_item(repo_id: str, *, private: bool = False, gated: bool = False) -> dict[str, Any]:
    return fill(
        part(APP, "POST /api/v1/sources/hf/search", 200, "items", "[]"),
        repo_id=repo_id,
        licence="cc-by-4.0",
        licences=["cc-by-4.0"],
        downloads=100,
        gated="auto" if gated else False,
        private=private,
    )


def _approval(id_: str, action: str, payload: dict[str, Any], n: int) -> dict[str, Any]:
    return instance(
        APP,
        "GET /api/v1/approvals/{approval_id}",
        200,
        id=id_,
        action=action,
        status="pending",
        requested_by="agent:miassist",
        payload=payload,
        summary=action,
        created_at=f"2026-11-16T00:00:{n:02d}Z",
        reason=None,
    )


@dataclass
class Dataworks:
    """The fake's state and switches."""

    hub: list[dict[str, Any]] = field(default_factory=lambda: [hub_item(PUBLIC)])
    import_mode: str = "ok"  # "ok" | "large" | "large_sync" | "running"
    plan_labels: int = 0
    #: ``valid`` in the build plan (``build_plan_service.plan_build``); False when the recipe does
    #: not fit the inputs (R2 review, OR2-int-5 F08).
    plan_valid: bool = True
    #: An answer miDataworks does not give today (the fail-closed test drains its violation).
    plan_override: dict[str, Any] | None = None
    build_mode: str = "ok"  # "ok" | "approval" | "empty" | "running" | "failed"
    #: The action a gated build waits as (``x-approval-actions`` of ``POST /versions``; 021-P3 added
    #: ``sensitivity_declare`` for a build that lowers sensitivity, ``build_action`` in miDataworks'
    #: ``services/agent_label_ledger.py``).
    build_approval_action: str = "agent_label_rows"
    files_status: str = "completed"  # the publish build's status (BuildStatus)
    leakage_pairs: int | None = None
    shortcut_warnings: list[dict[str, Any]] | None = None
    check_run: dict[str, Any] | None = None
    approval_status: str = "pending"
    publish_status: str | None = None
    sources: dict[str, dict[str, Any]] = field(default_factory=dict)
    datasets: dict[str, dict[str, Any]] = field(default_factory=dict)
    recipes: dict[str, dict[str, Any]] = field(default_factory=dict)
    versions: dict[str, dict[str, Any]] = field(default_factory=dict)
    #: R3 review fix (OR3-int-1), 2026-11-16: version id -> the versions whose labels taught its
    #: rules (``rule_source`` rows): never in ``VersionOut.inputs``, only in the manifest's
    #: transitive ``sources`` and in ``/lineage``'s ``rule_sources``, as miDataworks records them.
    rule_sources: dict[str, list[str]] = field(default_factory=dict)
    jobs: dict[str, dict[str, Any]] = field(default_factory=dict)
    builds: dict[str, dict[str, Any]] = field(default_factory=dict)
    approvals: list[dict[str, Any]] = field(default_factory=list)
    publishes: list[dict[str, Any]] = field(default_factory=list)
    ids: Any = field(default_factory=lambda: itertools.count(1))

    def new_id(self, prefix: str) -> str:
        return f"evalfx-{prefix}-{next(self.ids)}"

    # -- seeding -----------------------------------------------------------------------------------

    def seed_built(self, name: str = "support-chats", rows: int = 48_000) -> dict[str, Any]:
        """A source, dataset, recipe and built version, as after a finished build."""
        source = self._source(PUBLIC)
        dataset = self._dataset(name)
        version = self._version(dataset, rows, [{"kind": "source", "source_id": source["id"]}])
        return {"source": source, "dataset": dataset, "version": version}

    def _source(self, repo_id: str) -> dict[str, Any]:
        source = instance(
            APP,
            "GET /api/v1/sources/{source_id}",
            200,
            id=self.new_id("src"),
            kind="hf",
            state="ready",
            display_name=repo_id,
            repo_id=repo_id,
            splits=["train"],
            rows=48_200,
            licence_display="cc-by-4.0",
            # a public import carries no credential; Core's screen refuses any other tier
            # (integration OVN-miassist-int-15)
            token_tier="none",
            gated=None,
            files=[
                fill(
                    part(APP, "GET /api/v1/sources/{source_id}", 200, "files", "[]"),
                    split="train",
                    rows=48_200,
                    path="train.parquet",
                    columns=[{"name": "text"}, {"name": "label"}],
                )
            ],
        )
        self.sources[source["id"]] = source
        return source

    def _dataset(self, name: str) -> dict[str, Any]:
        dataset = instance(
            APP,
            "GET /api/v1/datasets/{dataset_id}",
            200,
            id=self.new_id("ds"),
            name=name,
            head_version_id=None,
            target_type="untyped",
            state="active",
            version_list=[],
        )
        self.datasets[dataset["id"]] = dataset
        return dataset

    def _version(
        self, dataset: dict[str, Any], rows: int, inputs: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """``VersionOut``; ``inputs`` as the build request named them (``InputRef``: ``kind``
        ``source`` or ``version`` with one id; ``schemas/versions.py:13-27``). A ``rule_source``
        ancestor is never here (``rule_sources``; R3 review fix OR3-int-1)."""
        assert all(i.get("kind") in ("source", "version") for i in inputs), inputs
        number = 1 + sum(1 for v in self.versions.values() if v["dataset_id"] == dataset["id"])
        split_schema = part(APP, "GET /api/v1/versions/{version_id}", 200, "splits", "[]")
        sizes = [("train", int(rows * 0.8), False), ("validation", int(rows * 0.1), True)]
        sizes.append(("test", rows - sizes[0][1] - sizes[1][1], True))
        version = instance(
            APP,
            "GET /api/v1/versions/{version_id}",
            200,
            id=self.new_id("ver"),
            dataset_id=dataset["id"],
            dataset_name=dataset["name"],
            number=number,
            state="completed",
            total_rows=rows,
            splits=[
                fill(split_schema, name=n, rows=r, held_out=h, path=f"{n}.parquet")
                for n, r, h in sizes
            ],
            drop_summary=[{"reason": "exact duplicate", "rows": 200}],
            recipe_id=None,
            is_head=True,
            inputs=[dict(i) for i in inputs],
        )
        self.versions[version["id"]] = version
        dataset["head_version_id"] = version["id"]
        dataset["head_number"] = number
        return version

    def _job(
        self, result: dict[str, Any], status: str = "completed", error: str | None = None
    ) -> str:
        job_id = self.new_id("job")
        self.jobs[job_id] = instance(
            APP,
            "GET /api/v1/jobs/{job_id}",
            200,
            id=job_id,
            status=status,
            result=result,
            error=error,
            kind="build",
        )
        return job_id

    # -- handlers ----------------------------------------------------------------------------------

    def install(self, fake: FakeApp) -> FakeApp:
        on = fake.on
        on("POST", "/api/v1/sources/hf/search", self.search)
        on("POST", "/api/v1/sources/hf/preview", self.preview)
        on("POST", "/api/v1/sources/hf", self.hf_import)
        on("GET", "/api/v1/sources", self.list_sources)
        on(
            "GET",
            "/api/v1/sources/{source_id}",
            lambda r: self._get(self.sources, r.path_params["source_id"], fake),
        )
        on(
            "GET",
            "/api/v1/jobs/{job_id}",
            lambda r: self._get(self.jobs, r.path_params["job_id"], fake),
        )
        on("GET", "/api/v1/datasets", self.list_datasets)
        on("POST", "/api/v1/datasets", self.create_dataset)
        on(
            "GET",
            "/api/v1/datasets/{dataset_id}",
            lambda r: self._get(self.datasets, r.path_params["dataset_id"], fake),
        )
        on(
            "GET",
            "/api/v1/operators/{name}",
            lambda r: instance(
                APP,
                "GET /api/v1/operators/{name}",
                200,
                name=r.path_params["name"],
                current_version="1.2.0",
                versions=[],
            ),
        )
        on("POST", "/api/v1/operators/{name}/{version}/validate", {"valid": True})
        on(
            "POST",
            "/api/v1/recipes/validate",
            lambda r: instance(APP, "POST /api/v1/recipes/validate", 200, valid=True),
        )
        on("GET", "/api/v1/recipes", self.list_recipes)
        on("POST", "/api/v1/recipes", self.save_recipe)
        on("POST", "/api/v1/versions/plan", self.plan)
        on("POST", "/api/v1/versions", self.build)
        on(
            "GET",
            "/api/v1/versions/{version_id}",
            lambda r: self._get(self.versions, r.path_params["version_id"], fake),
        )
        on("GET", "/api/v1/versions/{version_id}/manifest", self.manifest)
        on("GET", "/api/v1/versions/{version_id}/lineage", self.lineage)
        on("POST", "/api/v1/versions/{version_id}/publish-builds", self.files)
        on(
            "GET",
            "/api/v1/publish-builds/{build_id}",
            lambda r: self._get(self.builds, r.path_params["build_id"], fake),
        )
        on("GET", "/api/v1/versions/{version_id}/leakage", self.leakage)
        on("GET", "/api/v1/versions/{version_id}/shortcut-audit", self.shortcut)
        on("GET", "/api/v1/publish-check-runs/{check_run_id}", self.run)
        on("POST", "/api/v1/publishes", self.publish)
        on("GET", "/api/v1/publishes", self.list_publishes)
        on("GET", "/api/v1/approvals", self.list_approvals)
        on("GET", "/api/v1/approvals/{approval_id}", self.get_approval)
        self.fake = fake
        return fake

    def _reached(self, version_id: str) -> list[str]:
        """``version_finalize.transitive_sources`` over ``[*inputs, *ancestors]``."""
        found: list[str] = []
        todo, seen = [version_id], set()
        while todo:
            current = todo.pop()
            if current in seen or current not in self.versions:
                continue
            seen.add(current)
            for item in self.versions[current].get("inputs") or []:
                if item.get("kind") == "source":
                    found.append(item["source_id"])
                elif item.get("kind") == "version":
                    todo.append(item["version_id"])
            todo += self.rule_sources.get(current, [])
        return sorted(set(found))

    def manifest(self, r: Recorded) -> Any:
        version_id = r.path_params["version_id"]
        if version_id not in self.versions:
            return self.fake.error(404, "not_found", "no such version")
        version = self.versions[version_id]
        return instance(
            APP,
            "GET /api/v1/versions/{version_id}/manifest",
            200,
            format="dw.manifest/v1",
            version_id=version_id,
            number=version["number"],
            inputs=[dict(i) for i in version.get("inputs") or []],
            sources=[{"source_id": s, "kind": "hf"} for s in self._reached(version_id)],
        )

    def lineage(self, r: Recorded) -> Any:
        version_id = r.path_params["version_id"]
        if version_id not in self.versions:
            return self.fake.error(404, "not_found", "no such version")
        return instance(
            APP,
            "GET /api/v1/versions/{version_id}/lineage",
            200,
            version_id=version_id,
            inputs=[dict(i) for i in self.versions[version_id].get("inputs") or []],
            label_balancing=[],
            parent_version_id=None,
            children=[],
            rule_sources=[
                {"version_id": v, "number": self.versions[v]["number"]}
                for v in self.rule_sources.get(version_id, [])
                if v in self.versions
            ],
            steps=[],
        )

    def _get(self, table: dict[str, Any], key: str, fake: FakeApp) -> Any:
        if key not in table:
            return fake.error(404, "not_found", "no such row")
        return table[key]

    def _page(self, key: str, rows: list[dict[str, Any]], **extra: Any) -> dict[str, Any]:
        item = part(APP, key, 200, "items", "[]")
        names = set(item.get("properties", {}))
        kept = [fill(item, **{k: v for k, v in r.items() if k in names}) for r in rows]
        return instance(APP, key, 200, items=kept, total=len(kept), page=1, limit=50, **extra)

    def search(self, r: Recorded) -> Any:
        return instance(
            APP,
            "POST /api/v1/sources/hf/search",
            200,
            query=r.body.get("query"),
            licences=list(r.body.get("licences") or []),
            items=list(self.hub),
            total=len(self.hub),
        )

    def preview(self, r: Recorded) -> Any:
        schema = part(APP, "POST /api/v1/sources/hf/preview", 200, "splits", "[]")
        return instance(
            APP,
            "POST /api/v1/sources/hf/preview",
            200,
            repo_id=r.body["repo_id"],
            resolved_commit="evalfx-commit",
            configs=["default"],
            config="default",
            splits=[fill(schema, name="train", rows=48_200, bytes=9_000_000)],
            columns=[{"name": "text", "type": "string"}, {"name": "label", "type": "string"}],
            sample_rows=[{"text": "SECRET-ROW-TEXT", "label": "x"}],
            licence={"raw": "cc-by-4.0", "display": "cc-by-4.0", "origin": "card_data"},
            gated="false",  # the preview sends a lower-cased string or null (003's shape)
            unavailable=[],
        )

    def hf_import(self, r: Recorded) -> Any:
        repo = r.body["repo_id"]
        for source in self.sources.values():
            if source["repo_id"] == repo:
                return source
        if self.import_mode == "large_sync":
            return httpx.Response(
                409, json={"error": {"code": "import_confirmation_required", "message": "large"}}
            )
        accepted = "POST /api/v1/sources/hf"
        if self.import_mode == "large":
            job = self._job(
                {
                    "code": "import_confirmation_required",
                    "details": {"expected_bytes": 90_000_000_000},
                },
                status="failed",
                error="import_confirmation_required",
            )
            return httpx.Response(202, json=instance(APP, accepted, 202, job_id=job))
        source = self._source(repo)
        status = "running" if self.import_mode == "running" else "completed"
        if status == "running":
            del self.sources[source["id"]]
        job = self._job({"source_id": source["id"]}, status=status)
        return httpx.Response(202, json=instance(APP, accepted, 202, job_id=job))

    def list_sources(self, r: Recorded) -> Any:
        return self._page("GET /api/v1/sources", list(self.sources.values()))

    def list_datasets(self, r: Recorded) -> Any:
        q = r.params.get("q", "")
        found = [d for d in self.datasets.values() if q in d["name"]]
        return self._page("GET /api/v1/datasets", found)

    def create_dataset(self, r: Recorded) -> Any:
        dataset = self._dataset(r.body["name"])
        return httpx.Response(201, json=dataset)

    def list_recipes(self, r: Recorded) -> Any:
        q = r.params.get("q", "")
        return self._page(
            "GET /api/v1/recipes", [x for x in self.recipes.values() if q in x["name"]]
        )

    def save_recipe(self, r: Recorded) -> Any:
        rid, rev = self.new_id("rcp"), self.new_id("rev")
        self.recipes[rid] = {
            "id": rid,
            "name": r.body["name"],
            "head_revision_id": rev,
            "step_count": len(r.body["body"].get("steps", [])),
        }
        return httpx.Response(
            201,
            json=instance(
                APP,
                "POST /api/v1/recipes",
                201,
                recipe_id=rid,
                revision_id=rev,
                name=r.body["name"],
                body_bytes=10,
                note="saved",
                operators={},
                recipe_hash="evalfx-hash",
                revision_number=1,
                step_count=len(r.body["body"].get("steps", [])),
            ),
        )

    def plan(self, r: Recorded) -> Any:
        """``build_plan_service.plan_build`` (58087b1:141-215): labelling facts NESTED."""
        if self.plan_override is not None:
            return self.plan_override
        steps = (
            [{"step": 2, "operator": "label@1", "why": "calls a model"}] if self.plan_labels else []
        )
        labelling = fill(
            part(APP, "POST /api/v1/versions/plan", 200, "labelling"),
            counted_steps=steps,
            rows_counted=self.plan_labels,
            agent_needs_approval=False,
            threshold=5000,
        )
        body = instance(
            APP,
            "POST /api/v1/versions/plan",
            200,
            dataset_id=r.body["dataset_id"],
            recipe_revision_id=r.body["recipe_revision_id"],
            valid=self.plan_valid,
            labelling=labelling,
        )
        return body

    def build(self, r: Recorded) -> Any:
        dataset = self.datasets[r.body["dataset_id"]]
        if dataset.get("head_version_id"):
            return self.versions[dataset["head_version_id"]]
        accepted = "POST /api/v1/versions"
        if self.build_mode == "approval":
            approval = self._approve_later(self.build_approval_action, {"body": r.body})
            return httpx.Response(
                202,
                json={
                    "approval_id": approval["id"],
                    "status": "pending",
                    "action": self.build_approval_action,
                    "request_digest": "sha256:evalfx",
                    "expires_at": "2026-11-17T00:00:00+00:00",
                    "hint": "Waiting for the operator to approve this in miDataworks.",
                },
            )
        if self.build_mode == "failed":
            job = self._job({}, status="failed", error="the recipe failed on row 3")
            return httpx.Response(202, json=instance(APP, accepted, 202, job_id=job))
        rows = 0 if self.build_mode == "empty" else 48_000
        version = self._version(dataset, rows, list(r.body["inputs"]))
        if self.build_mode == "empty":
            version["drop_summary"] = [{"reason": "every row was a duplicate", "rows": 48_200}]
        status = "running" if self.build_mode == "running" else "completed"
        job = self._job({"version_id": version["id"], "number": version["number"]}, status=status)
        if status == "running":
            dataset["head_version_id"] = None
        return httpx.Response(202, json=instance(APP, accepted, 202, job_id=job))

    def files(self, r: Recorded) -> Any:
        version_id = r.path_params["version_id"]
        key = "POST /api/v1/versions/{version_id}/publish-builds"
        for build in self.builds.values():
            if build["version_id"] == version_id:
                return instance(
                    APP, key, 200, build_id=build["id"], reused=True, status=build["status"]
                )
        build_id = self.new_id("build")
        self.builds[build_id] = instance(
            APP,
            "GET /api/v1/publish-builds/{build_id}",
            200,
            id=build_id,
            version_id=version_id,
            status=self.files_status,
            files=[
                {"path": "train.parquet"},
                {"path": "validation.parquet"},
                {"path": "test.parquet"},
            ],
        )
        return httpx.Response(
            202,
            json=instance(APP, key, 202, build_id=build_id, reused=False, status=self.files_status),
        )

    def leakage(self, r: Recorded) -> Any:
        if self.leakage_pairs is None:
            return self.fake.error(404, "leakage_not_run", "no leakage report")
        result = fill(
            part(APP, "GET /api/v1/versions/{version_id}/leakage", 200, "result"),
            pairs_total=self.leakage_pairs,
            exact_pairs=self.leakage_pairs,
        )
        return instance(
            APP,
            "GET /api/v1/versions/{version_id}/leakage",
            200,
            id="evalfx-leak",
            kind="leakage",
            state="completed",
            result=result,
        )

    def shortcut(self, r: Recorded) -> Any:
        if self.shortcut_warnings is None:
            return self.fake.error(404, "audit_not_run", "no audit")
        item = part(APP, "GET /api/v1/versions/{version_id}/shortcut-audit", 200, "warnings", "[]")
        return instance(
            APP,
            "GET /api/v1/versions/{version_id}/shortcut-audit",
            200,
            warnings=[fill(item, **w) for w in self.shortcut_warnings],
        )

    def run(self, r: Recorded) -> Any:
        if self.check_run is None or self.check_run.get("id") != r.path_params["check_run_id"]:
            return self.fake.error(404, "not_found", "no such run")
        return instance(APP, "GET /api/v1/publish-check-runs/{check_run_id}", 200, **self.check_run)

    def _approve_later(self, action: str, payload: dict[str, Any]) -> dict[str, Any]:
        approval = _approval(self.new_id("apv"), action, payload, len(self.approvals))
        self.approvals.append(approval)
        return approval

    def publish(self, r: Recorded) -> Any:
        """``POST /publishes`` from an agent: stored as a pending ``hub_push`` (``payload`` is the
        handler's arguments, the body under ``body``; agent_origin.py:342-357)."""
        approval = self._approve_later("hub_push", {"body": dict(r.body)})
        return httpx.Response(
            202,
            json={
                "approval_id": approval["id"],
                "status": "pending",
                "action": "hub_push",
                "request_digest": "sha256:evalfx",
                "expires_at": "2026-11-17T00:00:00+00:00",
                "hint": "Waiting for the operator to approve this in miDataworks.",
            },
        )

    def add_publish(self, body: dict[str, Any], status: str, approval_id: str | None) -> None:
        self.publishes.insert(
            0,
            instance(
                APP,
                "GET /api/v1/publishes/{publish_id}",
                200,
                id=self.new_id("pub"),
                version_id=body["version_id"],
                repo_id=body["repo_id"],
                build_id=body.get("build_id", "evalfx-build"),
                status=status,
                requested_visibility=body["visibility"],
                approval_id=approval_id,
                kind="publish",
            ),
        )

    def decide(self, status: str, reason: str | None = None, *, row: bool = True) -> None:
        """The operator's decision on the newest hub_push (the fake's own step, never miAssist's).
        ``row=False``: approved and executing, before the executor has created the publish row."""
        approval = [a for a in self.approvals if a["action"] == "hub_push"][-1]
        approval["status"] = status
        approval["reason"] = reason
        if status in ("executing", "executed") and self.publish_status and row:
            self.add_publish(approval["payload"]["body"], self.publish_status, approval["id"])

    def list_publishes(self, r: Recorded) -> Any:
        mine = [p for p in self.publishes if p["version_id"] == r.params.get("version_id")]
        return self._page("GET /api/v1/publishes", mine)

    def list_approvals(self, r: Recorded) -> Any:
        status = r.params.get("status")
        found = [a for a in self.approvals if status is None or a["status"] == status]
        return instance(
            APP, "GET /api/v1/approvals", 200, approvals=found, total=len(found), page=1, limit=50
        )

    def get_approval(self, r: Recorded) -> Any:
        for a in self.approvals:
            if a["id"] == r.path_params["approval_id"]:
                return a
        return self.fake.error(404, "not_found", "no approval")


def fakes_with(dw: Dataworks) -> dict[str, FakeApp]:
    fakes = shaped_fakes(("midataworks",))
    dw.install(fakes["midataworks"])
    return fakes


WRITES = {"POST", "PUT", "PATCH", "DELETE"}
#: POSTs that write nothing (Core's ``POST_READS``) and the Hub calls (search and preview).
DRY_POSTS = {
    "/api/v1/operators/{name}/{version}/validate",
    "/api/v1/recipes/validate",
    "/api/v1/versions/plan",
}


def writes(fake: FakeApp) -> list[tuple[str, str | None]]:
    """The request log's writes, as (method, template)."""
    return [
        (r.method, r.template)
        for r in fake.requests
        if r.method in WRITES and r.template not in DRY_POSTS
    ]
