"""The whole own-data journey, all apps, against the stateful fakes (FPRD §11 items 1 and 4;
FTASKS 10.2). The operator's hands (approve, the run finishing, arming) are the test's."""

from __future__ import annotations

from typing import Any

from tests.playbooks.detector_probe.fakes import KEY, World
from tests.playbooks.detector_probe.journey import journey
from tests.playbooks.detector_probe.test_own_data import ARGS, REPO
from tests.playbooks.detector_probe.test_train_verdict import report

#: Goal-tool calls this journey takes on a client without forms (FTASKS 10.2 records the count).
GOAL_CALLS_WITHOUT_FORMS = 10


def test_own_data_journey_end_to_end() -> None:
    world = World()
    world.hub[REPO] = {"private": False, "gated": False, "licence": "cc-by-4.0", "bytes": 1000}
    world.models = [{"id": "evalfx-model", "status": "ready"}]
    calls: list[str] = []
    with journey(world=world, everyday_text_repo=REPO) as j:

        def goal(tool: str, args: dict[str, Any]) -> dict[str, Any]:
            calls.append(tool)
            return j.data(tool, args)

        proposal = goal("miassist_detector_start", {"description": "refund requests", "key": KEY})
        goal("miassist_detector_start", proposal["next_steps"][0]["args"])
        data = goal("miassist_detector_data", {k: v for k, v in ARGS.items() if v is not None})
        assert data["data"]["data_ready"] is True
        train = goal("miassist_detector_train", {"key": KEY})
        world.approve(train["approval"]["id"])
        started = goal("miassist_detector_train", train["approval"]["call_again_with"]["args"])
        run = world.runs[started["data"]["run_id"]]
        run.update(status="completed", selection={"selected": "evalfx-probe-1"})
        world.reports["evalfx-probe-1"] = {
            "probe": {"id": "evalfx-probe-1", "rung": 0},
            "evaluations": [],
        }
        verdict = goal("miassist_detector_verdict", {"key": KEY})
        world.approve(verdict["approval"]["id"])
        goal("miassist_detector_verdict", verdict["approval"]["call_again_with"]["args"])
        views = {v["role"] + (v.get("distribution") or ""): v["id"] for v in world.views}
        rep = report(2)
        rep["evaluations"] = [
            {"dataset_id": views[r], "metrics": {"scored": True, "ci": {"low": 0.9}}}
            for r in ("evalin_distribution", "everyday_text", "nonsense_text")
        ]
        world.reports["evalfx-probe-1"] = rep
        judged = goal("miassist_detector_verdict", {"key": KEY})
        assert judged["data"]["rung"] == 2
        deploy = goal("miassist_detector_deploy", {"key": KEY})
        world.approve(deploy["approval"]["id"])
        done = goal("miassist_detector_deploy", deploy["approval"]["call_again_with"]["args"])
        assert done["data"]["state"] == "awaiting_arm"
        world.sv_probes[done["data"]["miserver_probe_id"]]["armed"] = True
        status = j.data("miassist_status", {"playbook": "detector-probe", "subject": KEY})
        log = j.log()
    assert status["data"]["playbook"]["finished"] is True
    assert status["data"]["playbook"]["done"] == ["describe", "data", "train", "verdict", "deploy"]
    assert len(calls) == GOAL_CALLS_WITHOUT_FORMS
    paths = [entry[2] for entry in log]
    assert not [p for p in paths if p.endswith(("/arm", "/parity", "/consume")) or "/hub/" in p]
    for app, method, path, _, _, agent in log:
        assert agent is not None, (app, method, path)
