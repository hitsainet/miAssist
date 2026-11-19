"""FR-002.4, FR-002.6: the goals file, its hash and its approval state."""

from __future__ import annotations

import copy

import pytest
import yaml

from miassist_eval import fixtures, goals


def raw() -> dict:
    return yaml.safe_load(goals.GOALS_PATH.read_text())


def test_the_committed_goals_validate_against_the_fixtures() -> None:
    gs = goals.load(fixture_keys=fixtures.load().keys)
    assert [g["id"] for g in gs.goals] == ["detector-refund", "dataset-refund", "tone-warmer"]
    assert {g["playbook_id"] for g in gs.goals} == {"detector-probe", "dataset", "steering"}


def test_no_ssn_or_dlp_goal() -> None:
    text = goals.GOALS_PATH.read_text().lower()
    assert "ssn" not in text and "dlp" not in text.replace("non-dlp", "")


@pytest.mark.parametrize(
    "field",
    [
        "id",
        "playbook_id",
        "phrasings",
        "installation",
        "milestones",
        "first_useful_result",
        "final_message_check",
        "fixtures",
        "fairness",
        "required",
    ],
)
def test_a_goal_missing_any_field_fails(field: str) -> None:
    doc = raw()
    del doc["goals"][0][field]
    assert goals.check(doc), f"a goal without {field} validated"


def test_duplicate_goal_ids_fail() -> None:
    doc = raw()
    doc["goals"].append(copy.deepcopy(doc["goals"][0]))
    assert any("duplicate goal id" in f for f in goals.check(doc))


def test_a_goal_naming_an_unknown_fixture_fails() -> None:
    doc = raw()
    doc["goals"][0]["fixtures"].append("evalfx-not-there")
    found = goals.check(doc, fixtures.load().keys)
    assert any("evalfx-not-there" in f for f in found)


def test_hash_ignores_the_approval_block() -> None:
    doc = raw()
    before = goals.goal_set_sha256(doc)
    doc["approved"] = {
        "by": "operator",
        "on": "2026-11-20",
        "goal_set_sha256": before,
        "words": "ok",
    }
    assert goals.goal_set_sha256(doc) == before
    assert goals.GoalSet(doc).approved and goals.GoalSet(doc).headings() == []


def test_one_character_change_unapproves_the_set() -> None:
    doc = raw()
    sha = goals.goal_set_sha256(doc)
    doc["approved"] = {"by": "operator", "on": "2026-11-20", "goal_set_sha256": sha, "words": "ok"}
    doc["goals"][0]["phrasings"]["a"] = doc["goals"][0]["phrasings"]["a"].replace("I run", "I ran")
    gs = goals.GoalSet(doc)
    assert not gs.approved
    assert gs.headings() == [goals.NOT_APPROVED] == ["GOALS NOT APPROVED"]


def test_the_committed_set_is_not_yet_signed_off() -> None:
    """8.2 is the operator's; nothing here signs on his behalf."""
    assert goals.load().approved is False
