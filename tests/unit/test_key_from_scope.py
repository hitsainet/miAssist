"""``key_from_scope`` returns only a well-formed key (R2 review fix OR2-001-7, M-2, 2026-11-16).

Only KeyShim writes the scope state today, after its own check; this pins the second check
(defence in depth) so a later writer of the state cannot hand a tool a malformed key.
"""

from __future__ import annotations

from typing import Any

import pytest

from miassist.server.keyshim import STATE_KEY, key_from_scope

GOOD = "abcdefghijklmnopqrstuvwxyz"[:20] + "234567"


def test_a_well_formed_key_is_returned() -> None:
    assert key_from_scope({"state": {STATE_KEY: GOOD}}) == GOOD


@pytest.mark.parametrize(
    "scope",
    [
        {"state": {STATE_KEY: GOOD.upper()}},
        {"state": {STATE_KEY: GOOD + "a"}},
        {"state": {STATE_KEY: GOOD[:-1]}},
        {"state": {STATE_KEY: GOOD[:-1] + "1"}},
        {"state": {STATE_KEY: "../" + GOOD[3:]}},
        {"state": {STATE_KEY: 12345}},
        {"state": {}},
        {"state": None},
        {},
        "not a scope",
    ],
)
def test_anything_else_is_none(scope: Any) -> None:
    assert key_from_scope(scope) is None
