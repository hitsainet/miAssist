"""``MIASSIST_EVERYDAY_TEXT_REPO`` (FTDD §11, FTID §9; FTASKS 1.5)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from tests.support.app_factory import settings


def test_unset_by_default() -> None:
    assert settings().everyday_text_repo is None


@pytest.mark.parametrize(
    "value", ["evalfx/everyday", "evalfx/everyday:default", "evalfx/e:default:train"]
)
def test_accepts_a_repository(value: str) -> None:
    assert settings(everyday_text_repo=value).everyday_text_repo == value


@pytest.mark.parametrize("value", ["https://hf.co/x/y", "noslash", "a/b:c:d:e", "user:pw@x/y"])
def test_refuses_anything_else(value: str) -> None:
    with pytest.raises(ValidationError):
        settings(everyday_text_repo=value)


def test_blank_is_unset() -> None:
    assert settings(everyday_text_repo="  ").everyday_text_repo is None
