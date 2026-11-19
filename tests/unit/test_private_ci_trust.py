"""The private gate's wiring, read from the parsed workflow YAML (Foundation task 3.4).

Shape adapted from miForge's ``backend/tests/unit/test_private_ci_trust.py`` (docs/REUSE.md):

1. ``sync-to-clean.yml``'s ``gate`` job runs ``.github/scripts/private_ci_gate.py`` before the
   ``sync`` job, which ``needs`` it and publishes exactly the commit the gate passed.
2. ``REQUIRED_WORKFLOWS`` names every CI workflow that runs on ``main`` here, except
   ``docs-check.yml`` (the named exemption).
3. A missing run is a REFUSAL, never a pass (the gate script, run with a fake API).
4. On the mirror, ``docker-images.yml``'s build needs the ``private-ci`` job requiring the trailers.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = REPO_ROOT / ".github" / "workflows"
GATE_SCRIPT = REPO_ROOT / ".github" / "scripts" / "private_ci_gate.py"
EXEMPT = {
    "docs-check.yml": "validates the private 0xcc/ chain; it gates no image",
    # 002 FTASKS 9.2, 9.2a: dispatch/schedule only; they test today's app servers or a release
    # candidate's reference age, not the pushed commit's code.
    "eval-baseline.yml": "weekly baseline of today's app MCP servers (002 TD-7); gates no image",
    "eval-prerelease.yml": "dispatch-only pre-release reference-age run (002 FR-002.12a, A31)",
}


def load(name: str) -> dict[str, Any]:
    doc: dict[str, Any] = yaml.safe_load((WORKFLOWS / name).read_text())
    doc["on"] = doc.pop(True, doc.get("on"))  # PyYAML reads the bare key `on` as True
    return doc


def _runs_here(job: dict[str, Any]) -> bool:
    cond = str(job.get("if", ""))
    return not (
        "github.repository" in cond and "hitsainet/" in cond and "Onegaishimas/" not in cond
    )


def private_ci_workflows() -> set[str]:
    out = set()
    for path in sorted(WORKFLOWS.glob("*.yml")):
        doc = load(path.name)
        on = doc["on"] if isinstance(doc["on"], dict) else dict.fromkeys(doc["on"])
        if "pull_request" not in on or "push" not in on:
            continue
        branches = (on["push"] or {}).get("branches")
        if branches is not None and "main" not in branches:
            continue
        if any(_runs_here(job) for job in doc["jobs"].values()):
            out.add(path.name)
    return out - set(EXEMPT)


def test_required_workflows_name_every_ci_workflow() -> None:
    gate = load("sync-to-clean.yml")["jobs"]["gate"]
    required = {w.strip() for w in gate["env"]["REQUIRED_WORKFLOWS"].split() if w.strip()}
    assert required == private_ci_workflows()
    assert required == {"backend-tests.yml", "manual-ci.yml", "eval-tier1a.yml"}
    assert set(EXEMPT) <= {p.name for p in WORKFLOWS.glob("*.yml")}


def test_gate_runs_before_the_sync() -> None:
    jobs = load("sync-to-clean.yml")["jobs"]
    gate = jobs["gate"]
    run = next(s for s in gate["steps"] if s.get("id") == "gate")
    assert run["run"].strip() == "python .github/scripts/private_ci_gate.py"
    assert gate["permissions"]["actions"] == "read"
    sync = jobs["sync"]
    assert sync["needs"] == "gate" or "gate" in sync["needs"]
    assert "always()" not in str(sync.get("if", ""))
    pushers = {name for name, job in jobs.items() if "HITSAINET_SYNC" in json.dumps(job)}
    assert pushers == {"sync"}
    checkout = next(
        s for s in sync["steps"] if str(s.get("uses", "")).startswith("actions/checkout")
    )
    assert checkout["with"]["ref"] == "${{ needs.gate.outputs.sha }}"


def test_repository_guards_name_miassist() -> None:
    jobs = load("sync-to-clean.yml")["jobs"]
    for job in jobs.values():
        assert "Onegaishimas/miAssist" in job["if"] and "Onegaishimas/miassist" in job["if"]
    assert jobs["sync"]["env"]["MIRROR"] == "hitsainet/miAssist"


def _gate_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("private_ci_gate", GATE_SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _gate(runs: list[dict[str, Any]]) -> Any:
    module = _gate_module()

    def fake_get(path: str) -> dict[str, Any]:
        if "/jobs" in path:
            return {"jobs": []}
        return {"workflow_runs": runs}

    clock = iter(range(0, 10_000, 100))
    return module.Gate(
        "Onegaishimas/miAssist",
        "a" * 40,
        REPO_ROOT,
        get=fake_get,
        sleep=lambda _s: None,
        clock=lambda: float(next(clock)),
        timeout=1000,
        grace=200,
        interval=1,
    )


def test_missing_run_is_a_refusal() -> None:
    ok, message = _gate([]).check("backend-tests.yml")
    assert ok is False
    assert "no run" in message


def test_failed_run_refuses_and_passed_run_passes() -> None:
    base = {"event": "push", "status": "completed", "id": 1, "created_at": "x", "run_attempt": 1}
    assert _gate([{**base, "conclusion": "failure"}]).check("backend-tests.yml")[0] is False
    assert _gate([{**base, "conclusion": "success"}]).check("backend-tests.yml")[0] is True


def test_empty_required_list_refuses(monkeypatch: Any) -> None:
    module = _gate_module()
    monkeypatch.setenv("GITHUB_REPOSITORY", "Onegaishimas/miAssist")
    monkeypatch.setenv("SHA", "a" * 40)
    monkeypatch.setenv("REQUIRED_WORKFLOWS", "")
    assert module.main() == 1


def test_mirror_build_requires_the_trailers() -> None:
    doc = load("docker-images.yml")
    jobs = doc["jobs"]
    assert "private-ci" in jobs["build"]["needs"]
    script = "\n".join(s.get("run", "") for s in jobs["private-ci"]["steps"])
    assert "Private-CI: " in script and "Source-Commit: " in script and "exit 1" in script
    for job in jobs.values():
        assert "hitsainet/miAssist" in job["if"] and "Onegaishimas" not in job["if"]
