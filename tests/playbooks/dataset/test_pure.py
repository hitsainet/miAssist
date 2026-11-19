"""The dataset playbook's pure modules: the default recipe (3.2, FR-004.11), the dataset name (I3),
the plan's labelling read (3.4), the check verdict (4.2, 4.4; FR-004.13, FR-004.14) and the state
table (1.5; FTDD §7)."""

from __future__ import annotations

import re

import pytest

from miassist.guidance.loader import Guidance
from miassist.playbooks.dataset import checks, recipe
from miassist.playbooks.dataset.flow import STATES, Facts, derive

WORDS = Guidance().playbooks["dataset"].texts
VERSIONS = {"dedup_exact": "1.0.0", "split": "1.2.0"}

# -- recipe (3.2) -------------------------------------------------------------------------------


def test_default_recipe_without_held_out_split_and_with_label() -> None:
    body = recipe.default_recipe(["train"], "label", VERSIONS)
    assert body == {
        "format": "dw.recipe/v1",
        "steps": [
            {
                "operator": "dedup_exact",
                "version": "1.0.0",
                "params": {"collapse_whitespace": False},
            },
            {
                "operator": "split",
                "version": "1.2.0",
                "params": {
                    "split_names": ["train", "validation", "test"],
                    "split_fractions": [0.8, 0.1, 0.1],
                    "held_out": ["validation", "test"],
                    "stratify_by": ["label"],
                },
            },
        ],
    }


def test_default_recipe_without_label_has_no_stratify() -> None:
    params = recipe.default_recipe(["train"], None, VERSIONS)["steps"][1]["params"]
    assert "stratify_by" not in params and params["held_out"] == ["validation", "test"]


@pytest.mark.parametrize("splits", [["train", "test"], ["train", "validation"], ["TEST"]])
def test_default_recipe_keeps_a_held_out_source(splits: list[str]) -> None:
    body = recipe.default_recipe(splits, "label", VERSIONS)
    assert body["steps"][1]["params"] == {"mode": "keep_source"}
    assert [s["operator"] for s in body["steps"]] == ["dedup_exact", "split"]


def test_versions_come_from_the_caller() -> None:
    body = recipe.default_recipe(["train"], None, {"dedup_exact": "9.9.9", "split": "8.8.8"})
    assert [s["version"] for s in body["steps"]] == ["9.9.9", "8.8.8"]


def test_reasons_render_and_follow_the_choices() -> None:
    assert recipe.reason_keys(["train"], "label") == [
        "reason.dedup",
        "reason.split_new",
        "reason.stratify",
        "reason.name",
    ]
    assert recipe.reason_keys(["train", "test"], "label") == [
        "reason.dedup",
        "reason.split_keep",
        "reason.name",
    ]
    for key in ("reason.dedup", "reason.split_new", "reason.split_keep", "reason.stratify"):
        assert WORDS[key]


@pytest.mark.parametrize(
    "repo,taken,expected",
    [
        ("evalfx-org/Support_Chats", (), "support-chats"),
        ("evalfx-org/support-chats", ("support-chats",), "support-chats-2"),
        ("evalfx-org/support-chats", ("support-chats", "support-chats-2"), "support-chats-3"),
        ("evalfx-org/__x__", (), "x"),
        ("evalfx-org/" + "a" * 150, (), "a" * 96),
    ],
)
def test_proposed_name(repo: str, taken: tuple[str, ...], expected: str) -> None:
    assert recipe.proposed_name(repo, taken) == expected
    assert re.fullmatch(r"^[a-z0-9][a-z0-9-]{0,99}$", expected)


def _plan(**labelling: object) -> dict[str, object]:
    """miDataworks' plan (build_plan_service.py:187-202 at 58087b1): the facts under labelling."""
    facts: dict[str, object] = {
        "counted_steps": [],
        "rows_counted": 0,
        "agent_needs_approval": False,
    }
    return {"valid": True, "labelling": {**facts, **labelling}}


@pytest.mark.parametrize(
    "plan,labels",
    [
        (_plan(), None),
        (_plan(counted_steps=[{"step": 1, "operator": "label@1", "why": "x"}]), 0),
        (
            _plan(counted_steps=[{"step": 1, "operator": "label@1", "why": "x"}], rows_counted=12),
            12,
        ),
        (_plan(agent_needs_approval=True), 0),
    ],
)
def test_plan_labels(plan: dict[str, object], labels: int | None) -> None:
    assert recipe.plan_labels(plan) == labels


@pytest.mark.parametrize(
    "plan",
    [
        # the shape the fakes used before R1 (OR1-pb-1): facts at the top level, none nested
        {"valid": True, "counted_steps": [{"step": 2}], "rows_counted": 500},
        {"valid": True},
        {"valid": True, "labelling": None},
        {"valid": True, "labelling": {"counted_steps": [], "rows_counted": 0}},
        {
            "valid": True,
            "labelling": {"counted_steps": "1", "rows_counted": 0, "agent_needs_approval": False},
        },
        {
            "valid": True,
            "labelling": {"counted_steps": [], "rows_counted": True, "agent_needs_approval": False},
        },
        None,
        [],
    ],
)
def test_plan_labels_unreadable_fails_closed(plan: object) -> None:
    """R1 review fix (OR1-pb-1), 2026-11-16: facts that cannot be read never mean "no labels"."""
    with pytest.raises(recipe.PlanUnreadable):
        recipe.plan_labels(plan)


# -- checks (4.2, 4.4) -------------------------------------------------------------------------


def run(*results: tuple[str, str], status: str = "completed") -> dict[str, object]:
    return {
        "id": "evalfx-run",
        "status": status,
        "results": [
            {
                "check": c,
                "outcome": o,
                "reason": f"{c} said {o}",
                "next_step": "",
                "evidence": {"n": 3},
            }
            for c, o in results
        ],
    }


def test_no_run_shows_what_exists_and_the_rest_not_run() -> None:
    lines = checks.verdict(
        WORDS, "beginner", leakage={"result": {"pair_count": 14}}, shortcut={"warnings": []}
    )
    by = {line.id: line for line in lines}
    assert [line.id for line in lines] == list(checks.CHECK_IDS)
    assert by["C-3"].outcome == "amber" and "pairs=14" in by["C-3"].evidence
    assert by["C-7"].outcome == "green"
    assert {by[c].outcome for c in ("C-1", "C-2", "C-4", "C-5", "C-6", "C-8", "C-9")} == {"not_run"}
    assert checks.push_allowed(None) is None


@pytest.mark.parametrize(
    "outcomes,allowed",
    [
        ([("C-1", "green"), ("C-7", "green")], {"private": True, "public": True}),
        ([("C-1", "green"), ("C-7", "amber")], {"private": True, "public": False}),
        ([("C-2", "refused"), ("C-7", "amber")], {"private": False, "public": False}),
        ([("C-5", "note")], {"private": True, "public": True}),
    ],
)
def test_push_allowed_per_visibility(
    outcomes: list[tuple[str, str]], allowed: dict[str, bool]
) -> None:
    assert checks.push_allowed(run(*outcomes)) == allowed
    assert checks.push_allowed(run(*outcomes, status="running")) is None


@pytest.mark.parametrize("outcome", ["green", "note", "amber", "refused"])
@pytest.mark.parametrize("level", ["beginner", "expert"])
def test_every_check_and_outcome_renders(outcome: str, level: str) -> None:
    lines = checks.verdict(WORDS, level, check_run=run(*((c, outcome) for c in checks.CHECK_IDS)))
    assert [line.outcome for line in lines] == [outcome] * 9
    for line in lines:
        assert line.plain.startswith(line.id) and "n=3" in line.evidence


def test_unknown_check_falls_back_to_the_apps_text() -> None:
    lines = checks.verdict(WORDS, "beginner", check_run=run(("C-12", "amber")))
    extra = [line for line in lines if line.id == "C-12"]
    assert extra and "C-12 said amber" in extra[0].plain and "miDataworks says" in extra[0].plain


def test_c7_line_is_present_with_its_evidence() -> None:
    lines = checks.verdict(
        WORDS, "beginner", shortcut={"warnings": [{"column": "channel", "accuracy": 0.93}]}
    )
    c7 = next(line for line in lines if line.id == "C-7")
    assert c7.outcome == "amber" and "channel" in c7.evidence


@pytest.mark.parametrize(
    "licence,plain", [("cc-by-4.0", "with credit"), ("weird-1.0", "read it"), (None, "read it")]
)
def test_licence_plain(licence: str | None, plain: str) -> None:
    assert plain in checks.licence_plain(WORDS, licence)


# -- the no-overstatement scan (4.3; FR-004.14) --------------------------------------------------

OVERCLAIMS = ("clean", "unbiased", "safe", "guaranteed", "high-quality", "ready for production")


def test_no_overclaim_word_in_the_playbook_words() -> None:
    explain = Guidance().explain
    texts = list(WORDS.values())
    for tool in ("find", "build", "check", "publish"):
        for outcome in explain[f"miassist_dataset_{tool}"].outcomes.values():
            texts += list(outcome.model_dump().values())
    for text in texts:
        for word in OVERCLAIMS:
            assert not re.search(rf"\b{re.escape(word)}\b", text, re.IGNORECASE), (word, text)


def test_ready_to_publish_only_under_push_allowed() -> None:
    ready = [k for k, v in WORDS.items() if re.search("published (privately|publicly) now", v)]
    assert sorted(ready) == ["check.private_ok", "check.public_ok"]


def test_glossary_covers_the_playbooks_terms() -> None:
    glossary = Guidance().glossary
    for key in (
        "source",
        "dataset",
        "dataset-version",
        "recipe",
        "operator-step",
        "split",
        "held-out-split",
        "duplicate",
        "near-duplicate",
        "leakage",
        "shortcut",
        "publish-check",
        "check-outcome",
        "visibility",
    ):
        assert key in glossary, key


# -- the state table (1.5; FTDD §7) -------------------------------------------------------------

TABLE = [
    (Facts(), "nothing_chosen"),
    (Facts(source_named=True), "source_chosen"),
    (Facts(source_named=True, import_handoff="private"), "awaiting_import"),
    (Facts(source_named=True, import_handoff="large"), "awaiting_import"),
    (Facts(source_named=True, import_job="running"), "importing"),
    (Facts(source_ready=True), "imported"),
    (Facts(source_ready=True, dataset=True), "dataset_no_recipe"),
    (Facts(dataset=True, recipe_saved=True), "recipe_saved"),
    (Facts(dataset=True, recipe_saved=True, plan_labels=40), "awaiting_operator_build"),
    (Facts(dataset=True, recipe_saved=True, build_approval="pending"), "build_waiting"),
    (Facts(dataset=True, recipe_saved=True, build_job="running"), "building"),
    (Facts(dataset=True, version_state="ready", version_rows=0), "build_empty"),
    (Facts(dataset=True, build_job="failed"), "build_failed"),
    (Facts(dataset=True, version_state="ready", version_rows=10), "version_ready"),
    (Facts(version_state="ready", version_rows=10, files_status="running"), "checking"),
    (Facts(version_state="ready", version_rows=10, check_run_status="running"), "checking"),
    (
        Facts(version_state="ready", version_rows=10, files_status="completed"),
        "awaiting_publish_checks",
    ),
    (Facts(version_state="ready", version_rows=10, check_run_status="completed"), "checked"),
    (Facts(version_state="ready", version_rows=10, approval_status="pending"), "publish_waiting"),
    (Facts(version_state="ready", version_rows=10, approval_status="executing"), "publishing"),
    (Facts(approval_status="executed", publish_status="uploading"), "publishing"),
    (Facts(approval_status="executed", publish_status="published"), "published"),
    (Facts(publish_status="no_change"), "published"),
    (Facts(approval_status="rejected"), "rejected"),
    (Facts(approval_status="expired"), "expired"),
    (Facts(approval_status="failed"), "failed"),
    (Facts(approval_status="executed", publish_status="verification_failed"), "failed"),
]


@pytest.mark.parametrize("facts,state", TABLE, ids=[s for _, s in TABLE])
def test_state_table(facts: Facts, state: str) -> None:
    assert derive(facts) == state


def test_every_state_is_reachable_and_worded() -> None:
    assert {s for _, s in TABLE} == set(STATES)
    for state in STATES:
        assert f"state.{state}" in WORDS, state
