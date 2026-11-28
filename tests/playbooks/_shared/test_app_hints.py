"""App hints to miAssist next steps (FPRD §6; FTID §12; FTASKS 4.7, 2.5)."""

from __future__ import annotations

from miassist.playbooks._shared import app_hints

ARGS = {"key": "detector-refund"}


def test_next_steps_key_first() -> None:
    steps, said = app_hints.next_steps_of(
        {
            "next_steps": [
                {"tool": "evaluate_probe_monitor", "args": {"probe_id": "x"}, "why": "go"}
            ],
            "next": [{"tool": "start_probe_training_run"}],
        },
        ARGS,
    )
    assert steps == [{"tool": "miassist_detector_verdict", "args": ARGS, "why": "Get the verdict."}]
    assert said == []


def test_miworkbench_legacy_next() -> None:
    body = {
        "detail": {"code": "X", "next": [{"tool": "register_probe_dataset", "arguments": {"a": 1}}]}
    }
    steps, _ = app_hints.next_steps_of(body, ARGS)
    assert steps[0]["tool"] == "miassist_detector_data" and steps[0]["args"] == ARGS


def test_midataworks_legacy_next() -> None:
    steps, _ = app_hints.next_steps_of(
        {
            "next": {
                "tool": "dataworks_send_detector_sets",
                "args": {"set_ids": ["x"]},
                "why": "send",
            }
        },
        ARGS,
    )
    assert steps[0]["tool"] == "miassist_detector_data"


def test_miserver_error_next_tool_name() -> None:
    steps, _ = app_hints.next_steps_of(
        {"error": {"code": "X", "next": "miserver_import_probe"}}, ARGS
    )
    assert steps[0]["tool"] == "miassist_detector_deploy"


def test_unmapped_name_becomes_a_sentence_never_a_call() -> None:
    steps, said = app_hints.next_steps_of({"next": [{"tool": "miserver_arm_probe"}]}, ARGS)
    assert steps == [] and said == ["miserver arm probe"]
