"""``snapshot.read`` keeps only exact matches (FPRD FR-003.9, A22; FTASKS 2.1)."""

from __future__ import annotations

import json
from typing import Any

from tests.playbooks.detector_probe import fakes
from tests.playbooks.detector_probe.fakes import KEY, World
from tests.playbooks.detector_probe.journey import journey


def stray(world: World) -> dict[str, Any]:
    """The key's real detail, plus another behaviour's view the app should never list here."""
    detail = fakes._detail(world, KEY)
    other = {
        "id": "other-view-9",
        "name": "other-dlp",
        "role": "everyday_text",
        "behaviour": "other-dlp",
    }
    detail["adopted"]["views"].append(fakes._view_out(other))
    return detail


def test_a_stray_entry_in_an_app_answer_is_dropped() -> None:
    """Even when the app's own answer for the key carries another behaviour's view (a stray), the
    snapshot holds only the key's own (defence in depth beside the app's filter)."""
    world = World()
    world.behaviours[KEY] = {"key": KEY}
    world.views.append({"id": "evalfx-view-1", "role": "train", "behaviour": KEY})
    with journey(world=world) as j:
        j.fakes["miworkbench"].on(
            "GET",
            "/api/v1/probe-monitors/behaviours/{key}",
            lambda r: fakes.wb(f"GET {fakes.BEHAVIOUR.split(' ', 1)[1]}", 200, stray(world)),
        )
        doc = j.data("miassist_detector_data", {"key": KEY})
        status = j.data("miassist_status", {"playbook": "detector-probe", "subject": KEY})
    assert doc["data"]["state"] == "views_partial"
    assert "other-" not in json.dumps(doc) and "other-" not in json.dumps(status)


def test_reads_are_concurrent_and_one_down_app_is_named() -> None:
    world = World()
    world.behaviours[KEY] = {"key": KEY}
    with journey(world=world) as j:
        j.runtime.detector.mark_unreachable("midataworks", "connection refused")
        calm_doc = j.data("miassist_detector_data", {"key": KEY})
        j.runtime.detector.mark_unreachable("miworkbench", "connection refused")
        doc = j.data("miassist_detector_data", {"key": KEY})
    assert "unavailable" not in calm_doc, "own data does not need miDataworks to report"
    assert doc["unavailable"] == "miworkbench"
