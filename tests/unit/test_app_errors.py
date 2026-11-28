"""App answers and error-code normalisation (001 FR-17; FTASKS 5.3; A30)."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from miassist.adapters.base import AppError, Handoff, Pending, RawAnswer, Resource, Unavailable
from miassist.adapters.routes import ROUTES
from miassist.results.app_answers import classify, normalise_code

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
SCHEMA = json.loads(
    (FIXTURES.parent.parent / "docs/schemas/mistudio-result-language-v1.json").read_text()
)
ERROR_CODE = re.compile(SCHEMA["$defs"]["error_code"]["pattern"])
READ = ROUTES.get("miforge.list_runs")


def raw(status: int, body: object, text: str = "") -> RawAnswer:
    return RawAnswer(status, {}, body, text or json.dumps(body))


@pytest.mark.parametrize(
    ("app", "body", "code"),
    [
        (
            "midataworks",
            {"error": {"code": "UNPROCESSABLE", "message": "bad"}},
            "midataworks.unprocessable",
        ),
        ("miforge", {"error": {"code": "not_found", "message": "no run"}}, "miforge.not_found"),
        (
            "miserver",
            {"success": False, "error": {"code": "MODEL_NOT_LOADED", "message": "x"}},
            "miserver.model_not_loaded",
        ),
        ("miworkbench", {"detail": {"code": "mismatch", "message": "x"}}, "miworkbench.mismatch"),
        ("miworkbench", {"detail": "Not Found"}, "miworkbench.http_404"),
    ],
    ids=["dataworks", "forge", "server", "workbench-object", "workbench-string"],
)
def test_envelopes(app: str, body: object, code: str) -> None:
    answer = classify(app, READ, raw(404 if app == "miworkbench" else 422, body))
    assert isinstance(answer, AppError)
    assert answer.code == code
    assert ERROR_CODE.fullmatch(answer.code)


VECTORS = json.loads((FIXTURES / "error_code_vectors.json").read_text())["vectors"]


@pytest.mark.parametrize("vector", VECTORS, ids=[v["id"] for v in VECTORS])
def test_code_normalisation(vector: dict[str, str]) -> None:
    code = normalise_code(vector["app"], vector["app_code"])
    assert code == vector["line1_code"]
    assert len(code) <= 64 and ERROR_CODE.fullmatch(code)


def test_transport_statuses_are_unavailable() -> None:
    assert isinstance(classify("miforge", READ, raw(503, None, "Service Unavailable")), Unavailable)


def test_large_import_is_a_handoff() -> None:
    body = {"error": {"code": "import_confirmation_required", "message": "large"}}
    assert isinstance(classify("midataworks", READ, raw(409, body)), Handoff)


def test_success() -> None:
    answer = classify("miforge", READ, raw(200, {"items": []}))
    assert isinstance(answer, Resource) and answer.body == {"items": []}


def test_202_with_approval_is_pending() -> None:
    body = {"approval_id": "ap1", "status": "pending", "action": "run_start"}
    answer = classify("miforge", READ, raw(202, body))
    assert isinstance(answer, Pending)
    assert answer.approval["then"] == "server_runs" and answer.approval["id"] == "ap1"


# -- R1 review fix (OR1-001-7), 2026-11-16: 045's codes keep their own fix lines ---------------

FIXES = {
    "miworkbench.key_not_for_this_host": (
        "that stored key belongs to another host; the operator sets the key for this one"
    ),
    "miworkbench.unknown_body_field": "this route does not take that field; remove it",
    "miworkbench.model_files_not_on_disk": (
        "the model's files are not on disk; the operator downloads them in miWorkbench"
    ),
}


@pytest.mark.parametrize("code", sorted(FIXES))
def test_specific_fix_lines(code: str) -> None:
    from miassist.errors import render
    from miassist.guidance.loader import Guidance

    words = Guidance()
    fix = words.fix_for(code)
    assert fix == FIXES[code]
    assert fix != words.fix_for("app_error"), "the generic fallback replaced a specific fix"
    assert f"\nfix: {FIXES[code]}\n" in render(code, "refused", fix)
