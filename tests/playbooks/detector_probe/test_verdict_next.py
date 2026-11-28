"""The verdict's expert line names the one next step its rung allows (FPRD FR-003.17, §4.2).

ENH-012 acceptance, round 1 (review/enh012-acceptance, 2026-11-26): control E3-D25 made the
expert line say ``next: miassist_detector_deploy`` at every rung, and the whole suite stayed green:
the expert line's ``next`` was never read. Below rung 2 the honest next step is more data, never
deploying; deploying below rung 2 needs the person's own reason (FR-003.12).
"""

from __future__ import annotations

import pytest

from miassist.playbooks.detector_probe import verdict
from tests.playbooks.detector_probe.test_verdict import say


@pytest.mark.parametrize(
    "rung,nxt",
    [
        (0, "miassist_detector_data"),
        (1, "miassist_detector_data"),
        (2, "miassist_detector_deploy"),
        (3, "miassist_detector_deploy"),
    ],
)
def test_the_expert_line_names_the_next_step_its_rung_allows(rung: int, nxt: str) -> None:
    line = verdict.expert_line(verdict.VerdictFacts(rung=rung), say)
    assert line.endswith(f"next: {nxt}"), line
