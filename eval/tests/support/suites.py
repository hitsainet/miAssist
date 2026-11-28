"""A tier-1a suite over a hand-written dataset-refund take and the stub server under test."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from miassist_eval import cassette, goals
from miassist_eval.drivers.scripted import Step
from miassist_eval.suite import Plan, Suite
from tests.support import harness, stub_mcp

VERSION = {
    "id": "evalfx-v1",
    "dataset_id": "evalfx-ds-1",
    "dataset_name": "evalfx-refund-messages",
    "target_type": "classification",
    "number": 1,
    "state": "completed",
    "is_head": True,
    "superseded_by": None,
    "parent_version_id": None,
    "request_digest": "d",
    "inputs": [],
    "recipe_hash": "h",
    "recipe_revision_id": "evalfx-rr",
    "recipe_id": None,
    "seed": 1,
    "bindings": [],
    "rowkey_scheme": "k",
    "column_roles": {},
    "splits": [],
    "total_rows": 50,
    "total_bytes": 1000,
    "held_out_origin_version_id": None,
    "warnings": [],
    "drop_summary": [],
    "step_reports": [],
    "manifest_sha256": "m",
    "build_job_id": "evalfx-j",
    "created_by": "agent:miassist",
    "created_by_origin": "agent",
    "created_at": "2026-11-16T09:00:00Z",
}
CHECK_RUN = {
    "id": "evalfx-cr",
    "version_id": "evalfx-v1",
    "build_id": "evalfx-b",
    "repo_id": "evalfx-org/evalfx-refund",
    "requested_visibility": "private",
    "status": "completed",
    "results": [],
    "licence_table_version": None,
    "job_id": None,
    "created_at": "2026-11-16T09:00:00Z",
    "completed_at": "2026-11-16T09:01:00Z",
    "warnings": [],
}
#: PublishAccepted / PublishIn (miDataworks schemas/publishing.py at 58087b1), written by hand.
PUBLISH = {"publish_id": "evalfx-pub", "job_id": "evalfx-pj", "request_digest": "r"}
PUBLISH_IN = {
    "version_id": "evalfx-v1",
    "build_id": "evalfx-b",
    "repo_id": "evalfx-org/evalfx-refund",
}


def dataset_records() -> list[dict[str, Any]]:
    return [
        harness.record(
            0,
            "midataworks",
            "GET",
            "/api/v1/versions/evalfx-v1",
            "/api/v1/versions/{version_id}",
            200,
            VERSION,
        ),
        harness.record(
            1,
            "midataworks",
            "GET",
            "/api/v1/publish-check-runs/evalfx-cr",
            "/api/v1/publish-check-runs/{check_run_id}",
            200,
            CHECK_RUN,
        ),
        harness.record(
            2,
            "midataworks",
            "POST",
            "/api/v1/publishes",
            "/api/v1/publishes",
            201,
            PUBLISH,
            req_body=PUBLISH_IN,
        ),
    ]


DATASET_STEPS = [
    Step("call_app", {"app": "midataworks", "method": "GET", "path": "/api/v1/versions/evalfx-v1"}),
    Step(
        "call_app",
        {"app": "midataworks", "method": "GET", "path": "/api/v1/publish-check-runs/evalfx-cr"},
    ),
    Step(
        "call_app",
        {"app": "midataworks", "method": "POST", "path": "/api/v1/publishes", "body": PUBLISH_IN},
    ),
]


def suite(
    tmp_path: Path,
    *,
    records: list[dict[str, Any]] | None = None,
    steps: list[Step] | None = None,
    goal_id: str = "dataset-refund",
    sut: Any = None,
    goal_set: goals.GoalSet | None = None,
    client: str = "scripted",
    said: list[str] | None = None,
    **plan_kw: Any,
) -> Suite:
    root = tmp_path / "cassettes"
    take = harness.write_take(root, records if records is not None else dataset_records())
    plan = Plan(
        tier="1a",
        surface="miassist",
        client=client,
        goal_ids=[goal_id],
        takes={goal_id: take.path},
        steps={goal_id: steps if steps is not None else DATASET_STEPS},
        **plan_kw,
    )
    return Suite(
        plan=plan,
        sut=sut or stub_mcp.factory(),
        refs=harness.refs(),
        profiles=harness.profiles(),
        goal_set=goal_set or goals.load(),
        runs_dir=tmp_path / "runs",
        index=cassette.read_index(root),
        say=(said.append if said is not None else (lambda s: None)),
    )
