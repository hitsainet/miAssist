"""The second lock on a file-first call (A32): ``issue_approved_id`` issues an ``ApprovedId`` only
for a status read that shows ``approved``, and nothing else can make one.

ENH-012 acceptance, round 1 (review/enh012-acceptance, 2026-11-26): control E1-C10 removed the
status check inside ``issue_approved_id`` and the whole suite stayed green, because the adapter's
own check runs first. A later caller that skipped the adapter's check would then reach a GPU route
with a pending id; this pins the lock itself.
"""

from __future__ import annotations

import pytest

from miassist.adapters.base import ApprovedId, ProgrammingError, issue_approved_id


@pytest.mark.parametrize(
    "status", ["pending", "denied", "expired", "failed", "consumed", "executing", None, "APPROVED"]
)
def test_only_an_approved_status_read_issues_an_id(status: str | None) -> None:
    with pytest.raises(ProgrammingError):
        issue_approved_id("evalfx-ap-1", {"status": status})


def test_an_approved_read_issues_it_and_nothing_else_can() -> None:
    issued = issue_approved_id("evalfx-ap-1", {"status": "approved"})
    assert issued.id == "evalfx-ap-1" and issued.state["status"] == "approved"
    with pytest.raises(ProgrammingError):
        ApprovedId("evalfx-ap-1", {"status": "approved"}, object())
