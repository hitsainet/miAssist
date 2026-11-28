"""``evaluate_done_when`` over the vector table (001 FR-13, AC-13.4; FTASKS 11.3)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from miassist.contracts.playbook import DoneWhen
from miassist.playbooks.done_when import evaluate_done_when

VECTORS = json.loads(
    (Path(__file__).resolve().parents[1] / "fixtures/done_when_vectors.json").read_text()
)["vectors"]


@pytest.mark.parametrize("vector", VECTORS, ids=[v["id"] for v in VECTORS])
def test_vectors(vector: dict[str, Any]) -> None:
    assert evaluate_done_when(vector["predicate"], vector["data"]) is vector["expected"]


@pytest.mark.parametrize("vector", VECTORS, ids=[v["id"] for v in VECTORS])
def test_vectors_through_the_model(vector: dict[str, Any]) -> None:
    """The same answers from a validated ``done_when`` model (what providers hold)."""
    model = DoneWhen.model_validate(vector["predicate"])
    assert evaluate_done_when(model, vector["data"]) is vector["expected"]


def test_never_raises() -> None:
    assert evaluate_done_when({"pointer": 5, "op": "exists"}, {}) is False
    assert evaluate_done_when(None, {}) is False
    assert evaluate_done_when({"pointer": "/a", "op": "nope"}, {"a": 1}) is False


def test_both_outcomes_covered() -> None:
    assert {v["expected"] for v in VECTORS} == {True, False}
    assert {v["predicate"]["op"] for v in VECTORS} == {"exists", "truthy", "equals", "in", "gte"}
