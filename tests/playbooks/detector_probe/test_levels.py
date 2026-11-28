"""Identical side effects at both levels (FPRD FR-003.27, 001 AC-7.1; FTASKS 8.2)."""

from __future__ import annotations

from typing import Any

from tests.playbooks.detector_probe.journey import journey
from tests.playbooks.detector_probe.test_dataworks_route import journey_at
from tests.playbooks.detector_probe.test_own_data import ARGS, REPO, ready_world

SAME = ("data", "approval", "next_steps", "unavailable")


def own_data(level: str) -> tuple[list[Any], list[dict[str, Any]]]:
    world = ready_world()
    with journey(world=world, level=level, everyday_text_repo=REPO) as j:
        out = [
            j.data(
                "miassist_detector_start",
                {"description": "refund requests", "key": "detector-refund", "confirm": True},
            )
        ]
        world.behaviours.setdefault("detector-refund", {"key": "detector-refund"})
        out.append(
            j.data("miassist_detector_data", {k: v for k, v in ARGS.items() if v is not None})
        )
        world.models = [{"id": "evalfx-model", "status": "ready"}]
        out.append(j.data("miassist_detector_train", {"key": "detector-refund"}))
        return j.log(), out


def dataworks(level: str) -> tuple[list[Any], list[dict[str, Any]]]:
    with journey(world=journey_at("check", sets=["evalfx-set-1"]), level=level) as j:
        out = [
            j.data(
                "miassist_detector_data",
                {"key": "detector-refund", "route": "build_with_midataworks"},
            )
        ]
        out.append(
            j.data("miassist_status", {"playbook": "detector-probe", "subject": "detector-refund"})
        )
        return j.log(), out


def test_own_data_route_is_level_blind() -> None:
    (log_b, out_b), (log_e, out_e) = own_data("beginner"), own_data("expert")
    assert log_b == log_e and log_b
    for b, e in zip(out_b, out_e, strict=True):
        assert {k: b.get(k) for k in SAME} == {k: e.get(k) for k in SAME}
        assert "explain" in b and "explain" not in e


def test_dataworks_route_is_level_blind() -> None:
    (log_b, out_b), (log_e, out_e) = dataworks("beginner"), dataworks("expert")
    assert log_b == log_e and log_b
    for b, e in zip(out_b, out_e, strict=True):
        if "playbook" in (b.get("data") or {}):
            b, e = b["data"]["playbook"], e["data"]["playbook"]
            assert b == e
            continue
        assert {k: b.get(k) for k in SAME} == {k: e.get(k) for k in SAME}
