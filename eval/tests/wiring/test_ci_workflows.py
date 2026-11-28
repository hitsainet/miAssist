"""FR-002.16, FR-002.12a, R3M-9: the evaluation workflows read from the PARSED YAML (the live
object for CI)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from miassist_eval import cassette

REPO = Path(__file__).resolve().parents[3]
WORKFLOWS = REPO / ".github" / "workflows"
EVAL_WORKFLOWS = ("eval-tier1a.yml", "eval-baseline.yml", "eval-prerelease.yml")
GUARD = "github.repository == 'Onegaishimas/miAssist'"


def load(name: str) -> dict[str, Any]:
    doc: dict[str, Any] = yaml.safe_load((WORKFLOWS / name).read_text())
    doc["on"] = doc.pop(True, doc.get("on"))
    return doc


def env_of(doc: dict[str, Any]) -> dict[str, Any]:
    out = dict(doc.get("env") or {})
    for job in doc["jobs"].values():
        out.update(job.get("env") or {})
        for step in job.get("steps", []):
            out.update(step.get("env") or {})
    return out


def runs(doc: dict[str, Any]) -> list[str]:
    return [s["run"] for j in doc["jobs"].values() for s in j.get("steps", []) if "run" in s]


def approved_takes() -> list[dict]:
    return [e for e in cassette.read_index() if not e.get("retired_utc")]


def test_tier1a_runs_on_every_push_and_pull_request_with_no_paths_filter() -> None:
    on = load("eval-tier1a.yml")["on"]
    assert "push" in on and "pull_request" in on
    for trigger in ("push", "pull_request"):
        assert not (on[trigger] or {}).get("paths"), f"{trigger} has a paths filter"
        assert not (on[trigger] or {}).get("branches"), f"{trigger} is limited to branches"


def test_tier1a_runs_the_package() -> None:
    commands = runs(load("eval-tier1a.yml"))
    assert any("pytest" in c and "not paid" in c for c in commands)


def test_tier1a_is_a_required_workflow_of_the_private_gate() -> None:
    gate = load("sync-to-clean.yml")["jobs"]["gate"]
    assert "eval-tier1a.yml" in gate["env"]["REQUIRED_WORKFLOWS"].split()


@pytest.mark.parametrize("name", EVAL_WORKFLOWS)
def test_every_evaluation_job_carries_the_repository_guard(name: str) -> None:
    for job_id, job in load(name)["jobs"].items():
        assert str(job.get("if", "")).strip() == GUARD, f"{name}:{job_id}"


def test_prerelease_is_dispatch_only_and_sets_fail() -> None:
    doc = load("eval-prerelease.yml")
    assert set(doc["on"]) == {"workflow_dispatch"}
    assert env_of(doc).get("MIASSIST_EVAL_REF_AGE_MODE") == "fail"


def test_tier1a_never_sets_fail() -> None:
    assert env_of(load("eval-tier1a.yml")).get("MIASSIST_EVAL_REF_AGE_MODE", "warn") == "warn"


def test_the_cassette_switch_is_set_exactly_when_the_index_lists_an_approved_take() -> None:
    switch = env_of(load("eval-tier1a.yml")).get("MIASSIST_REQUIRE_CASSETTES") == "1"
    assert switch == bool(
        approved_takes()
    ), "MIASSIST_REQUIRE_CASSETTES=1 must be set exactly when INDEX.json lists an approved take"


def test_the_baseline_schedule_exists_exactly_when_a_baseline_take_does() -> None:
    on = load("eval-baseline.yml")["on"]
    assert "workflow_dispatch" in on
    has_take = any("baseline" in e["cassette_id"] for e in approved_takes())
    assert ("schedule" in on) == has_take


def test_no_tier1b_workflow_exists() -> None:
    names = {p.name for p in WORKFLOWS.glob("*.y*ml")}
    assert not any("1b" in n or "tier2" in n or "paid" in n for n in names)
