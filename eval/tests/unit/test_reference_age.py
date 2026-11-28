"""FR-002.12a (A31): the reference's age warns on ordinary pushes and fails only the pre-release
mode; the limit may only be lowered. Uses an injected clock through the suite's start path."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from miassist_eval import classes, openapi_ref, staleness
from miassist_eval.classes import Refusal
from tests.support import harness


def doc_aged(days: int, now: datetime) -> openapi_ref.RefDoc:
    d = harness.refs()["miforge"]
    return openapi_ref.build(
        "miforge",
        {"openapi": d.openapi, "fetched_on": (now - timedelta(days=days)).date().isoformat()},
    )


NOW = datetime(2026, 12, 20, 12, tzinfo=UTC)


def test_31_days_in_fail_mode_refuses() -> None:
    finding = staleness.check_age(doc_aged(31, NOW), NOW, 30)
    assert finding == "reference_too_old: miforge 31 days"
    with pytest.raises(Refusal) as caught:
        staleness.apply_age([finding], "fail")
    assert caught.value.cls == classes.REFERENCE_TOO_OLD


def test_31_days_in_warn_mode_runs_with_the_warning() -> None:
    printed = []
    finding = staleness.check_age(doc_aged(31, NOW), NOW, 30)
    assert staleness.apply_age([finding], "warn", printed.append) is True
    assert printed == ["WARNING reference_too_old: miforge 31 days"]


def test_29_days_neither() -> None:
    assert staleness.check_age(doc_aged(29, NOW), NOW, 30) is None
    assert staleness.apply_age([], "fail") is False


def test_a_limit_above_30_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MIASSIST_EVAL_REF_MAX_AGE_DAYS", "45")
    with pytest.raises(Refusal) as caught:
        staleness.max_age_days()
    assert caught.value.cls == classes.REFERENCE_TOO_OLD


def test_a_lower_limit_is_honoured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MIASSIST_EVAL_REF_MAX_AGE_DAYS", "7")
    assert staleness.max_age_days() == 7


def test_warn_is_the_default_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MIASSIST_EVAL_REF_AGE_MODE", raising=False)
    assert staleness.age_mode() == "warn"
