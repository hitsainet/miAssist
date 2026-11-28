"""FR-002.16 on the miAssist surface (CHAIN_PLAN A6 as amended, A30): next_steps, the seven approval
states, the four decide_in values, an error's lower-case code on line 1."""

from __future__ import annotations

from miassist_eval import shapes

GOOD = {
    "next_steps": [{"tool": "miassist_status", "args": {}, "why": "See where things stand."}],
    "approval": {
        "id": "a1",
        "status": "pending",
        "decide_in": "miworkbench",
        "then": "server_runs",
        "summary": "Evaluate the probe on the held-out set.",
    },
}


def test_the_contract_names_the_seven_states_and_four_apps() -> None:
    defs = shapes.contract()["$defs"]
    assert defs["approval_status"]["enum"] == [
        "pending",
        "approved",
        "executing",
        "executed",
        "failed",
        "rejected",
        "expired",
    ]
    assert defs["app_id"]["enum"] == ["miworkbench", "miserver", "midataworks", "miforge"]


def test_a_good_result_passes() -> None:
    assert shapes.check_miassist(GOOD, False, "ok") == []


def test_an_eighth_state_or_fifth_app_fails() -> None:
    bad = {**GOOD, "approval": {**GOOD["approval"], "status": "denied"}}
    assert shapes.check_miassist(bad, False, "")
    bad = {**GOOD, "approval": {**GOOD["approval"], "decide_in": "miassist"}}
    assert shapes.check_miassist(bad, False, "")


def test_a_malformed_next_step_fails() -> None:
    assert shapes.check_miassist({"next_steps": [{"tool": "x"}]}, False, "")


def test_an_error_line_1_needs_a_lower_case_code() -> None:
    assert shapes.check_miassist(None, True, "fixture_not_allowed: no\nfix: x\nnext: []") == []
    assert shapes.check_miassist(None, True, "midataworks.not_found: gone") == []
    assert shapes.check_miassist(None, True, "NotFound: gone")
    assert shapes.check_miassist(None, True, "Something went wrong")
