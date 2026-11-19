"""``VECTORS_VENDORED`` is true exactly when the vendored vector file exists (001 FTASKS 5.2a)."""

from __future__ import annotations

from tests.support.vectors import VECTORS_FILE, VECTORS_VENDORED


def test_flag_matches_the_file() -> None:
    assert VECTORS_VENDORED is VECTORS_FILE.is_file()
