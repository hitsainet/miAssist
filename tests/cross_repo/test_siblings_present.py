"""Every sibling is reachable for a full workstation run (Foundation task 1.2).

Skips loudly when a sibling is absent (the public mirror, CI); fails under a require switch.
"""

from __future__ import annotations

import pytest

from tests.support import siblings

pytestmark = pytest.mark.cross_repo


@pytest.mark.parametrize("sibling", siblings.SIBLINGS, ids=lambda s: s.key)
def test_sibling_checked_out(sibling: siblings.Sibling) -> None:
    root = siblings.require_root(sibling, "its cross-repo checks cannot run")
    assert (root / "docs").is_dir(), f"{root} does not look like a {sibling.name} checkout"
