"""FR-002.16a (M13, R1M-18; FTID §7.4): no model credential and no paid run in any workflow,
read from every PARSED workflow; ``--tier 1b`` and ``--tier 2`` refuse under CI."""

from __future__ import annotations

from pathlib import Path

import pytest

from miassist_eval import budget, ci_guard, cli

WORKFLOWS = Path(__file__).resolve().parents[3] / ".github" / "workflows"


def test_the_walker_sees_workflows_run_steps_and_secrets() -> None:
    ci_guard.self_check(ci_guard.load_workflows(WORKFLOWS))


def test_every_workflow_is_clean() -> None:
    assert ci_guard.findings(ci_guard.load_workflows(WORKFLOWS)) == []


def test_no_allowed_secret_is_a_model_word() -> None:
    assert not [s for s in ci_guard.ALLOWED_CI_SECRETS if ci_guard.MODEL_WORDS.search(s)]
    assert all(reason for reason in ci_guard.ALLOWED_CI_SECRETS.values())


@pytest.mark.parametrize(
    ("snippet", "why"),
    [
        (
            {
                "jobs": {
                    "j": {"env": {"ANTHROPIC_AUTH_TOKEN": "${{ secrets.ANTHROPIC_AUTH_TOKEN }}"}}
                }
            },
            "not an allowed",
        ),
        (
            {
                "jobs": {
                    "j": {
                        "env": {"CLAUDE_CODE_OAUTH_TOKEN": "${{ secrets.CLAUDE_CODE_OAUTH_TOKEN }}"}
                    }
                }
            },
            "not an allowed",
        ),
        ({"jobs": {"j": {"uses": "./.github/workflows/x.yml", "secrets": "inherit"}}}, "inherit"),
        ({"jobs": {"j": {"steps": [{"run": "echo '${{ toJSON(secrets) }}'"}]}}}, "whole secrets"),
        ({"jobs": {"j": {"steps": [{"run": "python -m miassist_eval run --tier 1b"}]}}}, "paid"),
        ({"jobs": {"j": {"steps": [{"run": "npx @anthropic-ai/claude-code -p hi"}]}}}, "paid"),
        ({"jobs": {"j": {"steps": [{"run": "claude -p 'x'"}]}}}, "paid"),
        ({"jobs": {"j": {"env": {"MY_KEY": "plain-value"}}}}, "credential-like"),
        (
            {"jobs": {"j": {"steps": [{"with": {"api-key": "${{ secrets.OPENAI_KEY }}"}}]}}},
            "not an allowed",
        ),
    ],
)
def test_each_violation_is_found(snippet: dict, why: str) -> None:
    found = ci_guard.findings({"planted.yml": snippet})
    assert any(why in f for f in found), found


@pytest.mark.parametrize("tier", ["1b", "2"])
@pytest.mark.parametrize("var", ["CI", "GITHUB_ACTIONS"])
def test_paid_tiers_refuse_under_ci(tier: str, var: str, monkeypatch, capsys) -> None:
    monkeypatch.setenv(var, "true")
    assert (
        cli.main(["run", "--tier", tier, "--surface", "miassist", "--client", "claude_code"]) == 2
    )
    assert "ci_refused" in capsys.readouterr().out


def test_tier1a_is_allowed_under_ci() -> None:
    budget.refuse_paid_in_ci("1a", {"CI": "true"})


def test_a_paid_suite_without_a_budget_refuses() -> None:
    from miassist_eval.classes import Refusal

    with pytest.raises(Refusal):
        budget.check_start("1b", 10, None, [], None)
    with pytest.raises(Refusal):
        budget.check_start("1b", 10, 5.0, [1.0], None)
    assert budget.check_start("1b", 10, 20.0, [1.0, 2.0], None) == 15.0
    assert budget.may_start_next(19.0, 2.0, 20.0) is False
