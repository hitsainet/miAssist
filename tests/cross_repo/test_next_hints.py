"""The vendored ``next-tool-hints.json`` is byte-identical to miServer's (001 FTASKS 4.6)."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.support import siblings

pytestmark = pytest.mark.cross_repo
COPY = Path(__file__).resolve().parents[2] / "docs/schemas/next-tool-hints.json"


def test_bytes() -> None:
    root = siblings.require_root(siblings.MISERVER, "next-tool-hints.json cannot be compared")
    assert (root / "docs/schemas/next-tool-hints.json").read_bytes() == COPY.read_bytes()
