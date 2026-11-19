"""Deploy and hand-off (FPRD FR-003.12, FR-003.6, FR-003.28; FTASKS 6.1 - 6.6)."""

from __future__ import annotations

import json
from typing import Any

from tests.playbooks.detector_probe.fakes import KEY, World
from tests.playbooks.detector_probe.journey import journey
from tests.playbooks.detector_probe.test_train_verdict import (
    VECTORS,
    filings,
    gpu_calls,
    report,
    trained,
    world_with_views,
)

NEVER = ("/arm", "/parity", "/hub/", "/consume", "/events/")


def judged(rung: int = 2) -> World:
    world = trained(world_with_views())
    world.reports["evalfx-probe-1"] = report(rung)
    return world


def never_called(j: Any) -> None:
    for app, fake in j.fakes.items():
        for r in fake.requests:
            assert not any(n in r.path for n in NEVER), (app, r.method, r.path)


def test_build_files_then_one_call_then_import_and_hand_off() -> None:
    world = judged()
    with journey(world=world) as j:
        first = j.data("miassist_detector_deploy", {"key": KEY})
        filed = filings(j)[0].body
        assert filed["tool_name"] == "build_probe_definition"
        assert filed["payload"] == VECTORS["28"]["payload"] | {"probe_id": "evalfx-probe-1"}
        assert gpu_calls(j, "/definition") == []
        world.approve(first["approval"]["id"])
        done = j.data("miassist_detector_deploy", first["approval"]["call_again_with"]["args"])
        builds = gpu_calls(j, "/definition")
        assert (
            len(builds) == 1
            and builds[0].headers["x-mistudio-approval-request"] == first["approval"]["id"]
        )
        imports = [r for r in j.fakes["miserver"].requests if r.path == "/api/probes/import"]
        assert len(imports) == 1 and imports[0].params == {"on_conflict": "fail"}
        assert done["data"]["state"] == "awaiting_arm" and done["data"]["armed"] is False
        assert done["data"]["waiting"][0]["kind"] == "operator_action"
        assert (
            "Probes page" in done["data"]["waiting"][0]["detail"]
            and "parity" in done["data"]["waiting"][0]["detail"]
        )
        again = j.data("miassist_detector_deploy", {"key": KEY})
        assert again["data"]["state"] == "awaiting_arm"
        assert len([r for r in j.fakes["miserver"].requests if r.path == "/api/probes/import"]) == 1
        world.sv_probes[done["data"]["miserver_probe_id"]]["armed"] = True
        watching = j.data("miassist_detector_deploy", {"key": KEY})
        never_called(j)
    assert watching["data"]["state"] == "watching" and watching["data"]["armed"] is True


def test_below_rung_two_needs_the_persons_reason() -> None:
    world = judged(rung=1)
    with journey(world=world) as j:
        asked = j.data("miassist_detector_deploy", {"key": KEY})
        assert asked["data"]["needs"] == ["below_rung2_reason"] and filings(j) == []
        j.data(
            "miassist_detector_deploy",
            {"key": KEY, "below_rung2_reason": "a pilot on test traffic only"},
        )
        filed = filings(j)[0].body["payload"]
    assert filed["acknowledge_below_rung2"] == {"reason": "a pilot on test traffic only"}


def test_import_conflict_adopts_the_existing_probe_by_identity() -> None:
    world = judged()
    world.sv_probes["evalfx-svprobe-0"] = {
        "id": "evalfx-svprobe-0",
        "name": "detector-refund-probe",
        "armed": False,
    }
    with journey(world=world) as j:
        first = j.data("miassist_detector_deploy", {"key": KEY})
        world.approve(first["approval"]["id"])
        done = j.data("miassist_detector_deploy", first["approval"]["call_again_with"]["args"])
    assert done["data"]["miserver_probe_id"] == "evalfx-svprobe-0"
    assert all(r.params.get("on_conflict") != "rename" for r in j.fakes["miserver"].requests)


def test_miserver_alone_with_a_probe_it_holds() -> None:
    world = World()
    world.sv_probes["evalfx-svprobe-7"] = {"id": "evalfx-svprobe-7", "name": "p", "armed": False}
    with journey(("miserver",), world=world) as j:
        doc = j.data("miassist_detector_deploy", {"probe": "evalfx-svprobe-7"})
        never_called(j)
    assert doc["data"]["state"] == "awaiting_arm"


def test_miserver_alone_with_a_hub_repo_is_the_operators_import() -> None:
    world = World()
    with journey(("miserver",), world=world) as j:
        doc = j.data("miassist_detector_deploy", {"hub_repo": "evalfx/refund-probe"})
        assert doc["data"]["state"] == "awaiting_hub_import"
        assert doc["data"]["waiting"][0]["kind"] == "operator_action"
        world.sv_probes["evalfx-svprobe-8"] = {
            "id": "evalfx-svprobe-8",
            "name": "p",
            "hf_id": "evalfx/refund-probe",
            "armed": False,
        }
        later = j.data("miassist_detector_deploy", {"hub_repo": "evalfx/refund-probe"})
        never_called(j)
        writes = j.writes("miserver")
    assert later["data"]["state"] == "awaiting_arm" and writes == []


def test_configured_but_down_miserver_answers_unavailable() -> None:
    """FR-003.6: down is not absent."""
    with journey(world=judged()) as j:
        j.runtime.detector.mark_unreachable("miserver", "connection refused")
        doc = j.data("miassist_detector_deploy", {"key": KEY})
    assert doc["unavailable"] == "miserver"


def test_absent_miserver_ends_calmly_at_the_verdict() -> None:
    with journey(("miworkbench",), world=judged()) as j:
        doc = j.data("miassist_detector_verdict", {"key": KEY})
    text = json.dumps(doc)
    assert doc["data"]["honest_end"] == (
        "Your detector is evaluated. Serving it needs miServer, which isn't part of this installation."
    )
    assert "unavailable" not in doc and "error" not in text.lower()


def test_no_rows_and_no_definition_echoed() -> None:
    world = judged()
    with journey(world=world) as j:
        first = j.data("miassist_detector_deploy", {"key": KEY})
        world.approve(first["approval"]["id"])
        world.built["evalfx-probe-1"] = {"name": "n", "head": {"weights": ["SECRET-WEIGHTS"]}}
        done = j.data("miassist_detector_deploy", first["approval"]["call_again_with"]["args"])
    assert "SECRET-WEIGHTS" not in json.dumps(done)
