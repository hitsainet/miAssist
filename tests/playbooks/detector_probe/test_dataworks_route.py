"""The miDataworks route (FPRD FR-003.7, FR-003.20; FTASKS 7.1 - 7.4)."""

from __future__ import annotations

import json
from typing import Any

import pytest

from tests.playbooks.detector_probe.fakes import KEY, World
from tests.playbooks.detector_probe.journey import journey
from tests.support import dw_journey

RESOLVE_TEXT = "miWorkbench is not configured on this miDataworks"


def journey_at(
    step: str | None,
    *,
    complete: bool = False,
    sets: list[str] | None = None,
    sends: list[dict[str, Any]] | None = None,
) -> World:
    """The status miDataworks gives when ``step`` is next, by ITS rule (R3 review fix OR3-int-3,
    2026-11-16): the counts of every earlier step are met (``dw_journey.counts_before``), and the
    journey, next and complete are derived from them by the fake. ``check`` stays next until a
    send exists, so ``send`` needs ``sends``. A step miDataworks does not have is served by hand
    (``rule: hand``), for the unknown-step fallback only."""
    world = World()
    world.behaviours[KEY] = {"key": KEY}
    known = {s["step"] for s in dw_journey.table()}
    counts = dw_journey.counts_before(None if complete else step if step in known else "check")
    counts["detector_sets"] = len(sets or []) if not complete else max(1, len(sets or []))
    counts["detector_sends"] = len(sends or []) if not complete else 1
    if step == "send" and not sends:
        raise AssertionError("miDataworks never makes 'send' next before a send exists")
    if step in known and step not in (None, "sets", "check", "send") and not complete:
        counts = dw_journey.counts_before(step)
    world.dw_status[KEY] = {
        "behaviour_key": KEY,
        "counts": counts,
        "objects": {
            "detector_sets": [{"id": s, "name": s, "archived": False} for s in sets or []],
            "detector_sends": list(sends or []),
        },
    }
    if step is not None and step not in known:
        world.dw_status[KEY].update(
            rule="hand",
            journey=[{"step": step, "title": "the app's own title"}],
            next={"step": step, "tool": "dataworks_x", "args": {}},
            complete=False,
        )
    return world


ARGS = {"key": KEY, "route": "build_with_midataworks"}
#: The person says the sets are complete: only then is the send filed (Confirmation fix C-int-2,
#: 2026-11-16, OVN-miassist-int-31).
SEND = {**ARGS, "confirm": True}


def sends(j: Any) -> list[Any]:
    return [r for r in j.fakes["midataworks"].requests if r.path == "/api/v1/detector-sets/send"]


def test_authoring_step_is_explained_and_waited_on() -> None:
    with journey(world=journey_at("rule_set")) as j:
        doc = j.data("miassist_detector_data", ARGS)
    assert doc["data"]["state"] == "dw_journey_step" and doc["data"]["journey_step"] == "rule_set"
    assert "Rule sets page" in doc["data"]["explain_step"]
    assert doc["data"]["waiting"][0]["kind"] == "operator_action" and j.writes() == []


def test_unknown_step_falls_back_to_the_apps_title_quoted() -> None:
    with journey(world=journey_at("brand_new_step")) as j:
        j.fakes["midataworks"].allow_departure(
            "$.journey[0].step", "a step a later miDataworks may add; 58087b1's enum has 13"
        )
        doc = j.data("miassist_detector_data", ARGS)
    assert doc["data"]["state"] == "dw_journey_step"  # R3 (OR3-int-5): not "described"
    assert doc["data"]["explain_step"] == "`the app's own title`"  # quoted (calm.quote)


def test_send_once_private_then_status_reads_only() -> None:
    world = journey_at("check", sets=["evalfx-set-1"])
    with journey(world=world) as j:
        first = j.data("miassist_detector_data", SEND)
        assert len(sends(j)) == 1 and sends(j)[0].body == {
            "set_ids": ["evalfx-set-1"],
            "visibility": "private",
        }
        assert (
            first["approval"]["then"] == "server_runs"
            and first["approval"]["decide_in"] == "midataworks"
        )
        assert "call_again_with" not in first["approval"]
        facts = first["data"]["approval_facts"]
        assert "private" in facts["cost"] and all(facts.values())
        again = j.data("miassist_detector_data", SEND)
        status = j.data("miassist_status", {"playbook": "detector-probe", "subject": KEY})
    assert len(sends(j)) == 1, "a repeat call with the pending row sends nothing"
    assert again["data"]["state"] == "dw_send_waiting"
    for r in j.fakes["midataworks"].requests:
        assert "approval" not in json.dumps(r.headers).lower() or r.method == "GET"
    assert status["data"]["playbook"]["waiting"][0]["kind"] == "approval"


def test_public_only_when_the_person_says_so() -> None:
    with journey(world=journey_at("check", sets=["evalfx-set-1"])) as j:
        j.data("miassist_detector_data", {**SEND, "visibility": "public"})
    assert sends(j)[0].body["visibility"] == "public"


def test_failed_send_is_shown_as_failed() -> None:
    world = journey_at("check", sets=["evalfx-set-1"])
    with journey(world=world) as j:
        first = j.data("miassist_detector_data", SEND)
        world.dw_approvals[first["approval"]["id"]]["status"] = "failed"
        doc = j.data("miassist_detector_data", SEND)
    assert doc["data"]["state"] == "failed" and len(sends(j)) == 1


def test_dataworks_only_ends_calmly_and_never_relays_the_resolve_text() -> None:
    world = journey_at("resolve")
    with journey(("midataworks",), world=world) as j:
        first = j.data("miassist_detector_data", ARGS)
        world.dw_status[KEY]["counts"] = dw_journey.counts_before(None)  # every step done
        done = j.data("miassist_detector_data", ARGS)
        resolved = [r for r in j.fakes["midataworks"].requests if r.path.endswith("/resolve")]
    for doc in (first, done):
        assert RESOLVE_TEXT not in json.dumps(doc) and "not configured" not in json.dumps(doc)
    assert len(resolved) == 1
    assert done["data"]["honest_end"] == (
        "Your detector's data is built and checked. Training it needs miWorkbench, which isn't part "
        "of this installation."
    )


def test_send_waits_for_the_training_app() -> None:
    with journey(("midataworks", "miserver"), world=journey_at("check", sets=["s"])) as j:
        doc = j.data("miassist_detector_data", ARGS)
    assert sends(j) == [] and doc["data"]["state"] == "data_checked"


def test_repeat_send_without_a_personal_link_sends_nothing() -> None:
    """No progress record: the repeat call finds the pending row by requester, action and digest."""
    with journey(world=journey_at("check", sets=["evalfx-set-1"]), key=None) as j:
        j.data("miassist_detector_data", SEND)
        j.data("miassist_detector_data", SEND)
    assert len(sends(j)) == 1


@pytest.mark.parametrize("state", ["failed", "cancelled", "rejected"])
def test_a_send_that_ended_without_its_views_is_failed(state: str) -> None:
    """R1 review fix (OR1-pb-13), 2026-11-16: miDataworks' terminal send states
    (``models/detector_send.py:36-44``) end the step; none reads as still running."""
    world = journey_at("check", sets=["evalfx-set-1"])
    send = {"id": "evalfx-send-1", "set_id": "evalfx-set-1", "state": state}
    world.dw_status[KEY]["objects"]["detector_sends"] = [{**send, "checks_refused": 0, "checks": 0}]
    world.dw_sends["evalfx-send-1"] = {"set_id": "evalfx-set-1", "state": state}
    with journey(world=world) as j:
        doc = j.data("miassist_detector_data", ARGS)
    assert doc["data"]["state"] == "failed", doc["data"]
    assert sends(j) == []
