"""Confirmation fixes to 003's miDataworks send (confirm-int, 2026-11-16).

C-int-1: OVN-miassist-int-28 made the send live at ``check``. A rejected or expired send was then
filed again on the next call whenever miAssist held no remembered id (no personal link): 003's
lookup searched miDataworks' list only for ``pending`` and ``executing``. The lookup now also finds
a closed send of the same sets (``include_closed``), the call reports it, and only ``ask_again``
sends again (FR-003.22). The first test is the confirmer's probe
(``confirm-int/probes/probes_c/test_c_send.py``), changed only to say the sets are complete
(C-int-2) and to name the state it reports.

C-int-2: miDataworks marks its sets step done at ONE set while the person may still be making the
rest, and nothing it answers says how many there will be; the send was filed at the first set. It
now waits for the person to say the sets are complete (``confirm: true``; OVN-miassist-int-31).
"""

from __future__ import annotations

from typing import Any

import pytest

from tests.playbooks.detector_probe.fakes import KEY
from tests.playbooks.detector_probe.journey import journey
from tests.playbooks.detector_probe.test_dataworks_route import ARGS, SEND, journey_at, sends

S1, S2 = "evalfx-set-1", "evalfx-set-2"
KEYS = pytest.mark.parametrize("key", [None, "default"])


def _kw(key: str | None) -> dict[str, Any]:
    return {"key": None} if key is None else {}


# -- C-int-1: a closed send is reported, and sent again only with ask_again ---------------------


@KEYS
@pytest.mark.parametrize("status", ["rejected", "expired"])
@pytest.mark.parametrize("repeat", [ARGS, SEND], ids=["plain", "confirm"])
def test_c_rejected_send_is_not_refiled_without_ask_again(key, status, repeat) -> None:
    """FR-003.22: after a rejection or expiry, miAssist files again only with ask_again. The send
    (now reachable at 'check', OVN-28) must follow it like 003's other gates; ``confirm`` is not
    ``ask_again``."""
    world = journey_at("check", sets=[S1])
    with journey(world=world, **_kw(key)) as j:
        j.data("miassist_detector_data", SEND)
        for a in world.dw_approvals.values():
            a["status"] = status
        doc = j.data("miassist_detector_data", repeat)
        assert len(sends(j)) == 1
    assert doc["data"]["state"] == status


@KEYS
@pytest.mark.parametrize("status", ["rejected", "expired"])
def test_the_closed_send_is_reported_and_ask_again_sends_once_more(key, status) -> None:
    """The closed send's result offers ``miassist_detector_data`` with ``ask_again`` (the live tool
    accepts it), and that call files exactly one new send with the same body."""
    world = journey_at("check", sets=[S1])
    with journey(world=world, **_kw(key)) as j:
        j.data("miassist_detector_data", SEND)
        for a in world.dw_approvals.values():
            a["status"] = status
        doc = j.data("miassist_detector_data", ARGS)
        offered = [s for s in doc["next_steps"] if s["tool"] == "miassist_detector_data"]
        assert offered and offered[0]["args"].get("ask_again") is True, doc["next_steps"]
        again = j.data("miassist_detector_data", {**ARGS, "ask_again": True})
        posted = sends(j)
        assert len(posted) == 2
        assert posted[1].body == posted[0].body == {"set_ids": [S1], "visibility": "private"}
        assert again["data"]["state"] == "dw_send_waiting"
        assert again["approval"]["id"] != next(iter(world.dw_approvals))
        # the new send is open: a plain repeat finds it and sends nothing more
        j.data("miassist_detector_data", SEND)
        assert len(sends(j)) == 2


@KEYS
def test_ask_again_never_sends_twice_while_a_send_is_open(key) -> None:
    """``ask_again`` lifts only the closed outcomes: an open send of the same sets is still found."""
    world = journey_at("check", sets=[S1])
    with journey(world=world, **_kw(key)) as j:
        j.data("miassist_detector_data", SEND)
        j.data("miassist_detector_data", {**SEND, "ask_again": True})
        assert len(sends(j)) == 1


# -- C-int-2: the send waits for the person to say the sets are complete ------------------------


@KEYS
def test_the_send_waits_until_the_person_says_every_set_exists(key) -> None:
    """At the first set miDataworks already says ``check``; miAssist files nothing until
    ``confirm: true``, then sends every live set the status names."""
    world = journey_at("check", sets=[S1])
    status = world.dw_status[KEY]
    with journey(world=world, **_kw(key)) as j:
        held = j.data("miassist_detector_data", ARGS)
        assert sends(j) == [] and world.dw_approvals == {}
        assert held["data"]["state"] == "dw_journey_step"
        assert held["data"]["journey_step"] == "check" and held["data"]["sets_to_send"] == 1
        assert "confirm: true" in held["data"]["explain_step"]
        assert held.get("approval") is None
        offered = held["next_steps"][0]
        assert offered["tool"] == "miassist_detector_data"
        assert offered["args"] == {"key": KEY, "route": "build_with_midataworks", "confirm": True}
        # the person makes the second set (one per sub-question) and says they are complete
        status["counts"]["detector_sets"] = 2
        status["objects"]["detector_sets"].append({"id": S2, "name": S2, "archived": False})
        j.data("miassist_detector_data", ARGS)
        assert sends(j) == []
        filed = j.data("miassist_detector_data", offered["args"])
        assert [r.body for r in sends(j)] == [{"set_ids": [S1, S2], "visibility": "private"}]
        assert filed["data"]["state"] == "dw_send_waiting"
        # a repeat without confirm finds the open send: nothing new, and not held
        again = j.data("miassist_detector_data", ARGS)
        assert len(sends(j)) == 1 and again["data"]["state"] == "dw_send_waiting"


def test_the_offered_call_keeps_public_visibility() -> None:
    with journey(world=journey_at("check", sets=[S1])) as j:
        held = j.data("miassist_detector_data", {**ARGS, "visibility": "public"})
        assert sends(j) == []
        args = held["next_steps"][0]["args"]
        assert args["visibility"] == "public" and args["confirm"] is True
        j.data("miassist_detector_data", args)
    assert sends(j)[0].body["visibility"] == "public"


# -- C-int-1, the gate: 003's GPU gates pass include_closed=True explicitly --------------------


def test_a_denied_training_without_a_personal_link_is_shown_not_refiled() -> None:
    """With no progress record, the gate's list lookup finds the denied request (miWorkbench says
    ``denied``) only because it passes ``include_closed=True``; nothing is filed again without
    ``ask_again`` (FR-003.22). Control C-int-1h."""
    from tests.playbooks.detector_probe.test_train_verdict import (
        filings,
        gpu_calls,
        world_with_views,
    )

    world = world_with_views()
    with journey(world=world, key=None) as j:
        first = j.data("miassist_detector_train", {"key": KEY, "model": "evalfx-model"})
        world.deny(first["approval"]["id"], "the card is busy tonight")
        shown = j.data("miassist_detector_train", {"key": KEY, "model": "evalfx-model"})
    assert len(filings(j)) == 1 and gpu_calls(j, "/runs") == []
    assert shown["data"]["state"] == "rejected"
