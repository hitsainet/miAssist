"""Only miServer's name conflict is adopted (FTID §3.5; R1 review fix OR1-pb-9).

ENH-012 acceptance, round 1 (review/enh012-acceptance, 2026-11-26): control E3-D13 dropped the
``details.code == "NAME_CONFLICT"`` comparison and the whole suite stayed green: the fake answers a
422 only for a conflict. miServer answers 422 ``VALIDATION_ERROR`` for other refusals of an
import too (``core/errors.py``), and adopting the probe that happens to hold the name after one of
those would hand the operator someone else's probe as this behaviour's. Each case is miServer's
envelope (``{"success": false, "data": null, "error": {code, message, details}}``).
"""

from __future__ import annotations

import json

import pytest

from miassist.adapters.base import AppError
from miassist.playbooks.detector_probe.actions import name_conflict


def answer(status: int, details: object) -> AppError:
    error = {"code": "VALIDATION_ERROR", "message": "refused", "details": details}
    body = json.dumps({"success": False, "data": None, "error": error})
    return AppError("miserver", status, "miserver.validation_error", "refused", body)


def test_the_name_conflict_is_a_conflict() -> None:
    assert name_conflict(answer(422, {"code": "NAME_CONFLICT", "name": "detector-x"}))


@pytest.mark.parametrize(
    "status,details",
    [
        (422, {"code": "SCHEMA_INVALID", "name": "detector-x"}),
        (422, {"user_message": "the definition's layer is out of range"}),
        (422, None),
        (409, {"code": "NAME_CONFLICT"}),
    ],
    ids=["another-code", "no-code", "no-details", "not-422"],
)
def test_any_other_refusal_is_not_a_conflict(status: int, details: object) -> None:
    assert not name_conflict(answer(status, details))
