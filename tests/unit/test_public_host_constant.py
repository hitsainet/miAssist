"""The committed values of the two code constants, pinned literally (A21, V-3; R3M-11).

Only push 001-P edits ``PUBLIC_HOST_APPROVED`` (to ``True``), in the same commit that edits this
pin (done: 001 FTASKS 14.5, 2026-11-17); only push 001-W edits ``MIWORKBENCH_A0_LIVE`` (to ``True``, after 045-A0 went live at
miWorkbench ``463b29bea`` on 2026-11-17). Flipping a constant alone turns this red.
"""

from __future__ import annotations

from miassist.web.exposure import MIWORKBENCH_A0_LIVE, PUBLIC_HOST_APPROVED


def test_public_host_constant() -> None:
    assert PUBLIC_HOST_APPROVED is True


def test_miworkbench_a0_constant() -> None:
    assert MIWORKBENCH_A0_LIVE is True
