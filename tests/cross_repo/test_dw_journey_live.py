"""The 003 fake's journey rule equals miDataworks' own (R3 review fix OR3-int-3, 2026-11-16).

``tests/fixtures/midataworks/journey.json`` is read by AST from the sibling's
``backend/src/services/behaviour/journey.py`` at the ref the pins use; a step, title, tool or
"done when" count that moves turns this red, so the fake can never again serve a journey miDataworks
does not. Skips loudly when the sibling is absent; fails under the require switch."""

from __future__ import annotations

import subprocess

import pytest

from tests.cross_repo.test_openapi_live import SIBLING, ref_for
from tests.support import dw_journey, siblings

pytestmark = pytest.mark.cross_repo


def test_the_vendored_journey_is_midataworks_own() -> None:
    root = siblings.require_root(SIBLING["midataworks"], "the fake's journey rule is unchecked")
    ref = ref_for("midataworks")
    source = subprocess.run(
        ["git", "-C", str(root), "show", f"{ref}:{dw_journey.SOURCE}"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert (
        dw_journey.extract(source) == dw_journey.table()
    ), f"miDataworks' journey at {ref} differs from tests/fixtures/midataworks/journey.json"
