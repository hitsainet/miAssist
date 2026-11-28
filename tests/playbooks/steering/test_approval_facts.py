"""Four facts in every steering approval (005 FPRD FR-005.17): what, cost (naming the model),
where, how to resume, at both levels.

ENH-012 acceptance (review/enh012-acceptance, 2026-11-26): no test checked this criterion, and the
combined check's approval named no model (``approval.combined``: "Cost: one GPU run of a short
reply and a baseline."). Red before the fix in the same commit.
"""

from __future__ import annotations

import pytest

from tests.playbooks.steering.fake import Steering
from tests.playbooks.steering.support import KEY_HASH, Session, data
from tests.playbooks.steering.test_acceptance import ONE, TWO
from tests.support.memory_store import MemoryStore


def _four_facts(summary: str, model: str) -> None:
    assert summary.split(".")[0], "what"
    what_and_cost = summary.partition("Where:")[0]
    assert summary.partition("Cost:")[2].partition("Where:")[0].strip(), f"no cost: {summary!r}"
    # the model load names its model as the "what" ("Load model X"); the GPU runs in their cost
    assert model in what_and_cost, f"names no model: {summary!r}"
    where = summary.partition("Where:")[2].partition("Then:")[0]
    assert where.strip(), f"no where: {summary!r}"
    assert summary.partition("Then:")[2].strip(), f"no how to resume: {summary!r}"


@pytest.mark.parametrize("level", ["beginner", "expert"])
async def test_every_approval_states_its_four_facts(keyed: MemoryStore, level: str) -> None:
    """FR-005.17: what, cost (which model), where and how to resume, for the sweep, the combined
    check and the model load, at both levels."""
    keyed.levels[str(KEY_HASH)] = level
    async with Session(Steering(), store=keyed) as s:
        sweep = await s.call("miassist_steering_try", {"feature": "evalfx-feat-1", "prompt": "Hi."})
        combined = await s.call(
            "miassist_steering_save", {"name": "pair", "features": TWO, "prompt": "Hi."}
        )
    model = "evalfx-model"
    _four_facts(sweep.structured_content["approval"]["summary"], model)
    _four_facts(combined.structured_content["approval"]["summary"], model)
    async with Session(Steering(model_status="ready"), store=keyed) as s:
        saved = data(await s.call("miassist_steering_save", {"name": "sunny", "features": ONE}))
        load = await s.call("miassist_steering_serve", {"cluster": saved["profile_id"]})
    assert data(load)["state"] == "model_load_waiting"
    _four_facts(load.structured_content["approval"]["summary"], model)
