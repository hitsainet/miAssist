"""FR-002.5: one test per rule, each with a phrasing that breaks only that rule; readability."""

from __future__ import annotations

import pytest

from miassist_eval import goals, lint, readability

CLEAN = "Our shop gets many messages. Please find the ones that ask for money back."
TOOLS = ["miassist_guide", "dataworks_list_datasets", "get"]


def rules(text: str, tools: list[str] = TOOLS) -> set[str]:
    findings = lint.check_text("g", "a", text, tools, [*lint.glossary_terms(), *lint.jargon()])
    return {f.rule for f in findings}


def test_clean_text_passes() -> None:
    assert rules(CLEAN) == set()


def test_rule_1_tool_name_whole_word_and_with_spaces() -> None:
    assert rules(CLEAN + " Use miassist_guide.") == {"tool_name"}
    # "datasets" is a glossary term since 004's entries (integration OVN-miassist-int-16): rule 2
    # also fires on this sentence, so rule 1 is asserted by membership.
    assert "tool_name" in rules(CLEAN + " Try dataworks list datasets.")


def test_rule_1_short_stop_words_are_skipped_visibly() -> None:
    assert lint.skipped_tool_names(TOOLS) == ["get"]
    assert rules(CLEAN + " Get it done.") == set()


def test_rule_2_glossary_and_jargon() -> None:
    assert rules(CLEAN + " Train a probe.") == {"glossary_term"}
    assert rules(CLEAN + " Pick a layer.") == {"glossary_term"}


def test_rule_3_app_names() -> None:
    assert rules(CLEAN + " Use miDataworks.") == {"app_name"}
    assert rules(CLEAN + " It runs in miStudio.") == set()


@pytest.mark.parametrize(
    "ident",
    [
        "m_1a2b3c4d",
        "pmr_abc",
        "123e4567-e89b-12d3-a456-426614174000",
        "0123456789abcdef0123",
        "v@2",
    ],
)
def test_rule_4_identifiers(ident: str) -> None:
    assert rules(f"{CLEAN} See {ident} now.") == {"identifier"}


def test_rule_5_steps() -> None:
    assert rules("Please help.\n1. Find the messages.") == {"steps"}
    assert rules("Please help.\n- Find the messages.") == {"steps"}


def test_rule_6_length() -> None:
    text = " ".join(["Our shop is busy."] * 40)
    assert len(text) > 600 and rules(text) == {"length"}


def test_rule_7_readability() -> None:
    text = (
        "Notwithstanding organisational considerations, comprehensive authorisation "
        "documentation necessitates administrative verification."
    )
    assert rules(text) == {"readability"}


@pytest.mark.parametrize(
    ("sentence", "grade"),
    [
        ("The cat sat on the mat.", -1.45),
        ("The quick brown fox jumps over the lazy dog.", 2.34),
        ("Students read the long report before class.", 4.0),
    ],
)
def test_readability_reference_sentences(sentence: str, grade: float) -> None:
    assert readability.fk_grade(sentence) == pytest.approx(grade, abs=0.5)


def test_the_committed_goals_pass_the_lint() -> None:
    gs = goals.load()
    found = lint.lint(gs.goals, gs.fixed_replies, [], lint.glossary_terms(), lint.jargon())
    assert found == [], [str(f) for f in found]


def test_glossary_is_read_from_core_as_data() -> None:
    terms = lint.glossary_terms()
    assert "probe" in terms and "steering" in terms
