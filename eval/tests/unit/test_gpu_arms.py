"""A41 (R3A-6): the partial arms read where the route reads, parsed the route's way; fail closed."""

from __future__ import annotations

import pytest

from miassist_eval import gpu_guard
from tests.support import harness

RECAL = ("POST", "/api/v1/probe-monitors/probes/{probe_id}/recalibrate")
CONTROL = ("POST", "/api/v1/trainings/{training_id}/control")


def req(query: dict | None = None, body: object = None) -> gpu_guard.Req:
    return gpu_guard.Req("POST", "/x", query or {}, {}, body)


def arm(key: tuple[str, str]) -> gpu_guard.Arm:
    a = harness.gpu_list()[key].arm
    assert a is not None
    return a


@pytest.mark.parametrize(
    "value", ["1", "true", "True", "TRUE", "yes", "on", "t", "y", "maybe", "2"]
)
def test_recut_windows_arms(value: str) -> None:
    assert gpu_guard.arm_holds(arm(RECAL), req({"recut_windows": value}))


@pytest.mark.parametrize("value", ["0", "false", "False", "no", "off", "f", "n"])
def test_recut_windows_false_spellings_do_not_arm(value: str) -> None:
    assert not gpu_guard.arm_holds(arm(RECAL), req({"recut_windows": value}))


def test_absent_recut_windows_takes_the_route_default() -> None:
    assert not gpu_guard.arm_holds(arm(RECAL), req({}))


def test_a_body_value_does_not_count_for_a_query_arm() -> None:
    assert not gpu_guard.arm_holds(arm(RECAL), req({}, {"recut_windows": True}))


def test_training_control_resume_arms_pause_does_not() -> None:
    assert gpu_guard.arm_holds(arm(CONTROL), req(body={"action": "resume"}))
    for off in ("pause", "stop", "stop_and_finalize"):
        assert not gpu_guard.arm_holds(arm(CONTROL), req(body={"action": off}))


def test_training_control_unknown_or_absent_action_arms() -> None:
    assert gpu_guard.arm_holds(arm(CONTROL), req(body={"action": "restart"}))
    assert gpu_guard.arm_holds(arm(CONTROL), req(body={}))
