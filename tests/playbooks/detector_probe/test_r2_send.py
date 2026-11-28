"""003's miDataworks send (R2 review). First: the send, approved by the operator (miDataworks runs it: ``executing``), then
repeated with and without the progress record: nothing new is sent (A18, A43).

R2 review fix (OR2-int-1), 2026-11-16: the repeat-call lookup searched miDataworks' ``pending``
approvals only, so a repeat without the progress record sent a second time while the first ran.
The reviewer's probe (review-int-r2 ``probes/test_r2_probe_send_dup.py``), adopted as the test.
"""

from __future__ import annotations

import hashlib

import pytest

from tests.playbooks.detector_probe.fakes import KEY
from tests.playbooks.detector_probe.journey import PERSON, journey
from tests.playbooks.detector_probe.test_dataworks_route import ARGS, SEND, journey_at, sends
from tests.support.memory_store import MemoryStore


@pytest.mark.parametrize("key", [None, "default"])
def test_repeat_send_after_approval_sends_nothing_new(key: str | None) -> None:
    world = journey_at("check", sets=["evalfx-set-1"])
    kw = {"key": None} if key is None else {}
    with journey(world=world, **kw) as j:
        j.data("miassist_detector_data", SEND)
        assert len(sends(j)) == 1
        for approval in world.dw_approvals.values():
            approval["status"] = "executing"
        j.data("miassist_detector_data", SEND)
    assert len(sends(j)) == 1, f"a second send was made: {len(sends(j))}"


# -- R2 review fix (OR2-int-5, F12), 2026-11-16: the progress record keeps the send's ids only ----

IDS = {
    "train_dataset_id": "evalfx-view-train",
    "eval_dataset_ids": ["evalfx-view-eval"],
    "calibration_dataset_id": "evalfx-view-cal",
}


def test_ids_keep_only_the_three_ids() -> None:
    """``_ids`` keeps exactly the three id keys, whatever else a run request carries."""
    from miassist.playbooks.detector_probe.actions import _ids

    extra = {**IDS, "prompt_text": "a person's words", "config": {"stride": 1}}
    assert _ids(extra) == IDS
    assert _ids(None) == {} and _ids(["not", "a", "mapping"]) == {}


def test_the_progress_record_holds_the_send_ids_and_nothing_else() -> None:
    """Wiring: a completed send's run request reaches the progress record through ``_ids``."""
    world = journey_at("rule_set", sets=["evalfx-set-1"])
    send = {"id": "evalfx-send-1", "set_id": "evalfx-set-1", "state": "completed"}
    world.dw_status[KEY]["objects"]["detector_sends"] = [{**send, "checks_refused": 0, "checks": 0}]
    world.dw_sends["evalfx-send-1"] = {
        "set_id": "evalfx-set-1",
        "state": "completed",
        "run_request": dict(IDS),
    }
    store = MemoryStore()
    with journey(world=world, store=store) as j:
        j.data("miassist_detector_data", ARGS)
    key_hash = hashlib.sha256(PERSON.encode()).hexdigest()
    state = store.progresses[(key_hash, "detector-probe", KEY)]["state"]
    assert state["run_request"] == IDS
