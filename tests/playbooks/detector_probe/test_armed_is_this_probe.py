"""Watching means THIS probe is armed (FPRD FR-003.12, FR-003.26; FTID §3.5).

ENH-012 acceptance, round 1 (review/enh012-acceptance, 2026-11-26): control E3-D22 read the first
armed probe in miServer's status as this behaviour's, and the whole suite stayed green: every
fixture with an armed probe armed only this one. With another probe armed and this one imported but
not armed, the journey waits on the operator's arming; it never reports someone else's counts.
"""

from __future__ import annotations

from tests.playbooks.detector_probe.fakes import KEY, World
from tests.playbooks.detector_probe.journey import journey
from tests.playbooks.detector_probe.test_status import PB, described, seeded


def test_another_armed_probe_is_not_this_one() -> None:
    world = described(World(), views=True)
    world.sv_probes["evalfx-svprobe-1"] = {"id": "evalfx-svprobe-1", "name": "p", "armed": False}
    world.sv_probes["evalfx-svprobe-9"] = {
        "id": "evalfx-svprobe-9",
        "name": "someone-elses",
        "armed": True,
        "paused_reason": None,
    }
    world.sv_events["evalfx-svprobe-9"] = [{"verdict": "fired"}] * 3
    with journey(world=world, store=seeded({"miserver_probe_id": "evalfx-svprobe-1"})) as j:
        doc = j.data("miassist_detector_deploy", {"key": KEY})
        answer = j.data("miassist_status", {"playbook": PB, "subject": KEY})
    assert doc["data"]["state"] == "awaiting_arm" and doc["data"]["armed"] is False
    assert "events_24h" not in doc["data"]
    assert answer["data"]["playbook"]["finished"] is False
