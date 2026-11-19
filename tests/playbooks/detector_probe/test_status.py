"""The status provider (FPRD FR-003.24 - FR-003.26; FTASKS 2.1, 2.4, 2.5, 2.6, 2.7, 2.8)."""

from __future__ import annotations

import hashlib
import json
from typing import Any
from unittest import mock

from miassist.playbooks import done_when as core_done_when
from tests.playbooks.detector_probe.fakes import KEY, World, other_entries
from tests.playbooks.detector_probe.journey import PERSON, journey
from tests.support.memory_store import MemoryStore

PB = "detector-probe"
VIEW_ROLES = [
    ("train", None),
    ("eval", "in_distribution"),
    ("calibration", None),
    ("everyday_text", None),
    ("nonsense_text", None),
]


def described(world: World, *, views: bool = False) -> World:
    world.behaviours[KEY] = {"key": KEY, "positive_meaning": "a refund request"}
    if views:
        for i, (role, dist) in enumerate(VIEW_ROLES):
            world.views.append(
                {
                    "id": f"evalfx-view-{i}",
                    "role": role,
                    "distribution": dist,
                    "behaviour": KEY,
                    "counts": {"rows": 100},
                }
            )
    return world


def seeded(state: dict[str, Any]) -> MemoryStore:
    store = MemoryStore()
    key_hash = hashlib.sha256(PERSON.encode()).hexdigest()
    store.progresses[(key_hash, PB, KEY)] = {"playbook_version": 1, "state": state}
    return store


def status(j: Any) -> dict[str, Any]:
    return j.data("miassist_status", {"playbook": PB, "subject": KEY})["data"]["playbook"]


def test_status_without_progress_equals_status_with_it() -> None:
    world = described(World(), views=True)
    with journey(world=world, store=seeded({"catalogued": KEY, "route": "my_labelled_data"})) as j:
        with_record = status(j)
    with journey(world=world, key=None) as j:
        without = status(j)
    assert (with_record["where"], with_record["next"]) == (without["where"], without["next"])
    assert (
        with_record["where"] == "train" and with_record["next"]["tool"] == "miassist_detector_train"
    )
    assert with_record["done"] == ["describe", "data"]


def test_status_reads_only_exact_matches() -> None:
    world = described(World(), views=True)
    other_entries(world)
    with journey(world=world) as j:
        answer = j.data("miassist_status", {"playbook": PB, "subject": KEY})
    assert "other-" not in json.dumps(answer)


def test_done_when_evaluated_once_per_step() -> None:
    """FR-003.25a: Core's evaluator, once per runnable step per status call."""
    world = described(World(), views=True)
    calls: list[Any] = []
    real = core_done_when.evaluate_done_when

    def counted(predicate: Any, data: Any) -> bool:
        calls.append((predicate.pointer, data))
        return real(predicate, data)

    with (
        journey(world=world) as j,
        mock.patch.object(core_done_when, "evaluate_done_when", counted),
    ):
        doc = status(j)
    assert [c[0] for c in calls] == ["/key", "/data_ready", "/trained", "/rung", "/armed"]
    assert doc["done"] == ["describe", "data"]


def test_watching_shows_counts_only() -> None:
    world = described(World(), views=True)
    world.sv_probes["evalfx-svprobe-1"] = {
        "id": "evalfx-svprobe-1",
        "name": "p",
        "armed": True,
        "paused_reason": None,
    }
    world.sv_events["evalfx-svprobe-1"] = [
        {"verdict": "fired", "context_text": "SECRET USER TEXT", "prompt": "SECRET"}
    ] * 3 + [{"verdict": "not_fired", "text": "SECRET USER TEXT"}] * 501
    with journey(world=world, store=seeded({"miserver_probe_id": "evalfx-svprobe-1"})) as j:
        doc = j.data("miassist_detector_deploy", {"key": KEY})
        answer = j.data("miassist_status", {"playbook": PB, "subject": KEY})
    assert doc["data"]["state"] == "watching"
    assert doc["data"]["events_24h"] == {"fired": "3", "not_fired": "500+", "not_scored": "0"}
    assert "SECRET" not in json.dumps(doc) and "SECRET" not in json.dumps(answer)
    assert answer["data"]["playbook"]["finished"] is True


def test_app_refusal_maps_to_lower_case_code() -> None:
    world = World()
    world.behaviours["x-taken"] = {"key": "x-taken"}
    with journey(world=world) as j:
        j.fakes["miworkbench"].on(
            "POST",
            "/api/v1/probe-monitors/behaviours",
            lambda r: __import__("httpx").Response(
                409,
                json={
                    "detail": {
                        "code": "BEHAVIOUR_KEY_TAKEN",
                        "message": "taken",
                        "next": [{"tool": "create_behaviour", "arguments": {}}],
                    }
                },
            ),
        )
        result = j.call(
            "miassist_detector_start",
            {"description": "refund requests", "key": "fresh-key", "confirm": True},
        )
    text = result["content"][0]["text"]
    assert result["isError"] is True
    line1, _fix, nxt = text.splitlines()[:3]
    assert line1.startswith("miworkbench.behaviour_key_taken:")
    assert nxt.startswith("next: ") and "miassist_detector_start" in nxt
    assert "create_behaviour" not in nxt


def test_floor_entry_passes_through_core_rate_limiter() -> None:
    limits = json.dumps({"detector.create_behaviour": {"count": 0, "window_s": 3600}})
    with journey(floor_limits=limits) as j:
        result = j.call(
            "miassist_detector_start",
            {"description": "refund requests", "key": "fresh-key", "confirm": True},
        )
        assert result["isError"] is True
        assert result["content"][0]["text"].startswith("floor_limit:")
        assert j.writes("miworkbench") == []


def test_unreachable_app_answers_unavailable() -> None:
    with journey() as j:
        j.runtime.detector.mark_unreachable("miworkbench", "connection refused")
        doc = j.data("miassist_detector_train", {"key": KEY})
    assert doc["unavailable"] == "miworkbench" and doc["reason"] == "connection refused"


def test_status_while_watching_reports_counts_and_reason() -> None:
    world = described(World(), views=True)
    world.sv_probes["evalfx-svprobe-1"] = {
        "id": "evalfx-svprobe-1",
        "name": "p",
        "armed": True,
        "paused_reason": "the model is not loaded",
    }
    world.sv_events["evalfx-svprobe-1"] = [{"verdict": "fired", "text": "SECRET"}] * 2
    with journey(world=world, store=seeded({"miserver_probe_id": "evalfx-svprobe-1"})) as j:
        doc = status(j)
    assert "fired 2 times" in doc["expected"] and "`the model is not loaded`" in doc["expected"]
    assert "SECRET" not in json.dumps(doc)
