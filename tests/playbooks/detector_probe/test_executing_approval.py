"""An approved request the app runs itself reads as running, never as no request (OR2-int-1).

ENH-012 acceptance, round 1 (review/enh012-acceptance, 2026-11-26): control E3-D20 removed
``executing`` from the flow's waiting statuses and the whole suite stayed green. miDataworks runs an
approved send itself (``pending -> executing -> executed``); without the line the send's approval
reads as nothing at all (``None``), so the journey's state no longer says the operator approved it
and miDataworks is sending. R2's ``test_r2_send.py`` pinned the repeat lookup, not this reading.
"""

from __future__ import annotations

import pytest

from miassist.playbooks.detector_probe import flow
from miassist.playbooks.detector_probe.flow import StepState as S
from miassist.playbooks.detector_probe.snapshot import Snapshot


@pytest.mark.parametrize(
    "status,state",
    [
        ("pending", S.DW_SEND_WAITING),
        ("executing", S.DW_SEND_RUNNING),
        ("approved", S.DW_SEND_RUNNING),
    ],
)
def test_the_send_approval_reads_as_its_state(status: str, state: S) -> None:
    snap = Snapshot(key="evalfx-key", approvals={"send": {"id": "apr_1", "status": status}})
    found = flow._approval_state(snap, "send", S.DW_SEND_WAITING, S.DW_SEND_RUNNING)
    assert found is not None and (found.state, found.step, found.kind) == (state, "data", "send")
