"""``MiAssistError`` and the error-code pattern (Foundation task 2.3; A30)."""

from __future__ import annotations

import pytest

from miassist.errors import ERROR_CODE_PATTERN, MiAssistError, valid_code


@pytest.mark.parametrize(
    "code", ["unknown_arguments", "floor_limit", "midataworks.not_found", "a", "x9_y.z_1"]
)
def test_valid(code: str) -> None:
    assert valid_code(code)
    assert MiAssistError(code, "m").code == code


@pytest.mark.parametrize(
    "code", ["", "Upper", "9lead", "a.b.c", "a-b", "a.", ".a", "UNPROCESSABLE", "x" * 65]
)
def test_invalid(code: str) -> None:
    assert not valid_code(code)
    with pytest.raises(ValueError):
        MiAssistError(code, "m")


def test_pattern_is_a30s() -> None:
    assert ERROR_CODE_PATTERN == r"^[a-z][a-z0-9_]*(\.[a-z0-9_]+)?$"


def test_fields() -> None:
    err = MiAssistError("floor_limit", "too many", fix="wait an hour", next=[{"tool": "x"}])
    assert (err.message, err.fix, err.next) == ("too many", "wait an hour", [{"tool": "x"}])
