"""Shared builders for the evaluation's tests: real references and profiles, hand-written cassettes.

The cassettes are written here, by hand, never generated from the reference (FTDD §10: the two
sides of a staleness check must not come from one source).
"""

from __future__ import annotations

import copy
from functools import cache
from pathlib import Path
from typing import Any

import yaml

from miassist_eval import cassette, gpu_guard, openapi_ref
from miassist_eval.edge import Edge

EVAL_ROOT = Path(__file__).resolve().parents[2]
PROFILE_DIR = EVAL_ROOT / "route_profiles"
HEADERS = {
    "miworkbench": {"X-MiStudio-Agent": "miassist"},
    "miserver": {"X-miLLM-Agent": "agent:miassist"},
    "midataworks": {"X-Dataworks-Agent": "agent:miassist"},
    "miforge": {"X-Miforge-Agent": "agent:miassist"},
}


@cache
def _refs() -> dict[str, openapi_ref.RefDoc]:
    return {a: openapi_ref.load(a) for a in openapi_ref.APPS}


def refs() -> dict[str, openapi_ref.RefDoc]:
    return dict(_refs())


@cache
def _profiles() -> dict[str, dict[str, Any]]:
    return {a: yaml.safe_load((PROFILE_DIR / f"{a}.yaml").read_text()) for a in openapi_ref.APPS}


def profiles() -> dict[str, dict[str, Any]]:
    return copy.deepcopy(_profiles())


@cache
def gpu_list() -> gpu_guard.GpuList:
    return gpu_guard.load(_refs()["miworkbench"], _profiles()["miworkbench"].get("gpu_arms"))


def edge(surface: str = "miassist", **kw: Any) -> Edge:
    return Edge(surface=surface, refs=refs(), profiles=profiles(), gpu=gpu_list(), **kw)


def record(
    seq: int,
    app: str,
    method: str,
    path: str,
    route: str,
    status: int,
    body: Any,
    query: dict[str, str] | None = None,
    req_body: Any = None,
    headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    return {
        "seq": seq,
        "app": app,
        "app_version": "test",
        "time": "2026-11-16T09:00:00+00:00",
        "request": {
            "method": method,
            "path": path,
            "route": route,
            "query": query or {},
            "headers": dict(HEADERS[app]),
            "body": req_body,
        },
        "answer": {"status": status, "headers": headers or {}, "body": body},
    }


def cassette_doc(records: list[dict[str, Any]], name: str = "test-take") -> dict[str, Any]:
    return {"format": cassette.FORMAT, "name": name, "source": "recorded", "records": records}


def fairness_block(passed: bool = True) -> dict[str, Any]:
    return {
        "checked_utc": "2026-11-16T09:00:00+00:00",
        "lists_read": ["midataworks /api/v1/datasets"],
        "matches": [] if passed else ["midataworks: x"],
        "passed": passed,
    }


def write_take(
    root: Path,
    records: list[dict[str, Any]],
    fairness: dict[str, Any] | None = None,
    index: bool = True,
    take: str = "t1",
) -> cassette.Take:
    take_dir = root / "goal" / "miassist" / take
    doc = cassette_doc(records)
    manifest = {
        "cassette_id": f"goal-miassist-{take}",
        "goal_id": "goal",
        "surface": "miassist",
        "take": take,
        "recording_run_id": "run-1",
        "recorder_version": "0.1.0",
        "started_utc": "2026-11-16T09:00:00+00:00",
        "ended_utc": "2026-11-16T09:10:00+00:00",
        "apps": {
            a: {"base_path": "", "openapi_sha256": _refs()[a].sha256, "version": "test"}
            for a in {r["app"] for r in records}
        },
        "fairness": fairness if fairness is not None else fairness_block(),
        "allowed_ids": [],
    }
    cassette.write_take(
        take_dir,
        doc,
        manifest,
        {"run_id": "run-1"},
        {a: _refs()[a].sha256 for a in manifest["apps"]},
        {a: {"status": "ok"} for a in manifest["apps"]},
    )
    loaded = cassette.Take(
        take_dir, __import__("json").loads((take_dir / "MANIFEST.json").read_text()), doc
    )
    if index:
        cassette.append_index(root, loaded, "2026-11-16T09:11:00+00:00")
    return loaded
