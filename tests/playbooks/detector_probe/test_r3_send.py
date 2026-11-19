"""003's miDataworks route after review round 3 (review-int-r3, 2026-11-16).

- R3 review fix (OR3-int-3): miDataworks' own journey rule (vendored, pinned by
  ``tests/cross_repo/test_dw_journey_live.py``) keeps ``check`` next until a send exists; with live
  sets miAssist files the send, whose filing runs the checks (``send_service.prepare``).
- R3 review fix (OR3-int-2): every version the send would publish passes Core's lineage screen.
- R3 review fix (OR3-int-4): the summary states the visibility the body sends (SW01); an
  archived set is never sent (SW05).
- R3 review fix (OR3-int-5): the miServer probe is adopted by its EXACT name (SW06); the app's
  journey title is quoted within its bound (SW10).
"""

from __future__ import annotations

from typing import Any

import pytest

from tests.playbooks.detector_probe.fakes import KEY
from tests.playbooks.detector_probe.journey import journey
from tests.playbooks.detector_probe.test_dataworks_route import ARGS, SEND, journey_at, sends
from tests.playbooks.detector_probe.test_deploy import judged
from tests.support import dw_journey

SET = "evalfx-set-1"
VERSION = f"evalfx-dwver-{SET}"


# -- OR3-int-3: the real journey rule, walked to the send --------------------------------------


def test_the_real_journey_walks_from_the_sets_to_the_send_and_on() -> None:
    world = journey_at("sets")
    status = world.dw_status[KEY]
    with journey(world=world) as j:
        first = j.data("miassist_detector_data", ARGS)
        assert first["data"]["journey_step"] == "sets" and sends(j) == []
        # the operator creates a set in miDataworks: miDataworks' rule now says "check"
        status["counts"]["detector_sets"] = 1
        status["objects"]["detector_sets"] = [{"id": SET, "name": SET, "archived": False}]
        assert dw_journey.walk(KEY, status["counts"])["next"]["step"] == "check"
        filed = j.data("miassist_detector_data", SEND)  # the person says the sets are complete
        assert len(sends(j)) == 1 and sends(j)[0].body["set_ids"] == [SET]
        assert filed["data"]["state"] == "dw_send_waiting"
        again = j.data("miassist_detector_data", ARGS)  # still waiting: nothing new
        assert len(sends(j)) == 1 and again["data"]["state"] == "dw_send_waiting"


def test_checks_that_refuse_keep_the_step_with_their_reason_and_file_nothing() -> None:
    world = journey_at("check", sets=[SET])
    world.dw_send_refused = {
        "code": "D-3",
        "title": "Label mapping covers every value",
        "reason": "the value 'maybe' is not mapped",
    }
    with journey(world=world) as j:
        doc = j.data("miassist_detector_data", SEND)
    assert doc["data"]["state"] == "dw_journey_step" and doc["data"]["journey_step"] == "check"
    assert "the value 'maybe' is not mapped" in doc["data"]["explain_step"]
    assert world.dw_approvals == {}, "an approval was filed although the checks refused"
    assert doc.get("approval") is None


# -- OR3-int-2: the lineage screen before the send ---------------------------------------------


def credentialed(world: Any, how: str) -> None:
    world.dw_sources["evalfx-dwsrc-private"] = {"token_tier": "stored"}
    if how == "direct":
        world.dw_versions[VERSION] = {"sources": ["evalfx-dwsrc-private"]}
    elif how == "rule_source":  # only in the manifest's sources and /lineage, never in inputs
        world.dw_versions["evalfx-dwver-teacher"] = {"sources": ["evalfx-dwsrc-private"]}
        world.dw_versions[VERSION] = {"rule_sources": ["evalfx-dwver-teacher"]}
    elif how == "input_version":
        world.dw_versions["evalfx-dwver-parent"] = {"sources": ["evalfx-dwsrc-private"]}
        world.dw_versions[VERSION] = {"version_inputs": ["evalfx-dwver-parent"]}
    elif how == "borrowed":
        world.dw_versions["evalfx-dwver-sibling"] = {"sources": ["evalfx-dwsrc-private"]}
        world.dw_sets[SET] = {
            "borrowed_roles": [
                {
                    "id": "r-b",
                    "role": "test",
                    "version_id": "evalfx-dwver-sibling",
                    "version_number": 1,
                    "version_state": "completed",
                    "dataset_id": None,
                    "dataset_name": None,
                }
            ]
        }


@pytest.mark.parametrize("how", ["direct", "rule_source", "input_version", "borrowed"])
def test_a_set_whose_version_lineage_holds_a_credentialed_source_is_never_sent(how: str) -> None:
    world = journey_at("check", sets=[SET])
    credentialed(world, how)
    with journey(world=world) as j:
        doc = j.call("miassist_detector_data", SEND)
        assert sends(j) == [], "the send was filed"
    assert doc["isError"] is True and "source_needs_operator" in str(doc["content"])


def test_a_set_that_cannot_be_read_is_never_sent() -> None:
    world = journey_at("check", sets=[SET])
    world.dw_sets[SET] = {"roles": []}
    with journey(world=world) as j:
        doc = j.call("miassist_detector_data", SEND)
        assert sends(j) == []
    assert doc["isError"] is True and "source_unchecked" in str(doc["content"])


def test_a_public_lineage_is_screened_then_sent() -> None:
    world = journey_at("check", sets=[SET])
    with journey(world=world) as j:
        j.data("miassist_detector_data", SEND)
        reads = [r.path for r in j.fakes["midataworks"].requests if r.method == "GET"]
    assert len(sends(j)) == 1
    assert f"/api/v1/detector-sets/{SET}" in reads
    assert f"/api/v1/versions/{VERSION}/manifest" in reads
    assert f"/api/v1/versions/{VERSION}/lineage" in reads
    assert "/api/v1/sources/evalfx-dwsrc-public" in reads


# -- OR3-int-4 (SW01, SW05): the reviewer's probes -----------------------------------------------


@pytest.mark.parametrize("visibility", ["public", "private"])
def test_send_summary_names_the_visibility_sent(visibility: str) -> None:
    with journey(world=journey_at("check", sets=[SET])) as j:
        doc = j.call("miassist_detector_data", {**SEND, "visibility": visibility})
        assert sends(j)[0].body["visibility"] == visibility
    sc = doc["structuredContent"]
    assert f"as a {visibility} repository" in sc["approval"]["summary"]
    assert sc["data"]["approval_facts"]["cost"].endswith(f"as a {visibility} repository.")


def test_an_archived_set_is_not_sent() -> None:
    world = journey_at("check", sets=[SET, "evalfx-set-old"])
    world.dw_status[KEY]["objects"]["detector_sets"][1]["archived"] = True
    with journey(world=world) as j:
        j.data("miassist_detector_data", SEND)
        posted = sends(j)
    assert posted and posted[0].body["set_ids"] == [SET]


# -- OR3-int-5 (SW06, SW10) ----------------------------------------------------------------------


def test_the_conflicting_probe_is_adopted_by_its_exact_name_not_a_decoy() -> None:
    world = judged()
    world.sv_probes["evalfx-svprobe-decoy"] = {
        "id": "evalfx-svprobe-decoy",
        "name": "old-detector-refund-probe-copy",  # holds the name; listed first
        "armed": False,
    }
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


def test_the_apps_journey_title_is_quoted_within_its_bound() -> None:
    world = journey_at("brand_new_step")
    world.dw_status[KEY]["journey"] = [{"step": "brand_new_step", "title": "x" * 500}]
    with journey(world=world) as j:
        j.fakes["midataworks"].allow_departure(
            "$.journey[0].step", "a step a later miDataworks may add (the fallback)"
        )
        doc = j.data("miassist_detector_data", ARGS)
    assert 0 < len(doc["data"]["explain_step"]) <= 122
