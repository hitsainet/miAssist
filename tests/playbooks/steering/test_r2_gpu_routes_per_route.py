"""Each enabled steering GPU route, on the PRODUCTION registry, files through ``/mcp/approvals``
first, is never called without an ``ApprovedId``, and is called once with the approved id after.

R2 review fix (OR2-int-3), 2026-11-16: the rule was pinned only generically (Core's
``test_file_first.py``); no 005 test failed when Core's step 7 accepted any id, because the
playbook always passes one. The reviewer's per-route probe (review-int-r2
``probes/test_r2_gpu_routes_per_route.py``), adopted as the permanent regression."""

from __future__ import annotations

from typing import Any

import pytest

from miassist.adapters.base import ProgrammingError
from miassist.adapters.routes import ROUTES
from tests.playbooks.steering import support
from tests.playbooks.steering.support import Session

FILE = "/api/v1/mcp/approvals"
SWEEP = "/api/v1/steering/async/sweep"
COMBINED = "/api/v1/steering/async/combined"
TWO = [{"feature": "evalfx-feat-1", "strength": 1.0}, {"feature": "evalfx-feat-2", "strength": 0.5}]


@pytest.fixture(autouse=True)
def production_registry(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(support, "gpu_registry", lambda: ROUTES)


@pytest.mark.parametrize(
    "rid,action",
    [("miworkbench.steer_sweep", "steer_sweep"), ("miworkbench.steer_combined", "steer_combined")],
)
async def test_route_is_file_first_and_refuses_without_an_approved_id(
    rid: str, action: str
) -> None:
    route = ROUTES.get(rid)
    assert route.file_first and route.approval_action == action
    async with Session() as s:
        client = s.deps.runtime.clients["miworkbench"]
        for bad in (None, "evalfx-ap-1"):
            with pytest.raises(ProgrammingError) as exc:
                await client.call(route, json={}, approval_id=bad)  # type: ignore[arg-type]
            assert "ApprovedId" in str(exc.value)
        assert s.log("miworkbench", "POST", route.path) == []


async def _call(s: Session, rid: str, **kw: Any) -> Any:
    if rid == "sweep":
        return await s.call(
            "miassist_steering_try", {"feature": "evalfx-feat-1", "prompt": "Hi.", **kw}
        )
    return await s.call(
        "miassist_steering_save", {"name": "pair", "features": TWO, "prompt": "Hi.", **kw}
    )


@pytest.mark.parametrize(
    "which,path,action", [("sweep", SWEEP, "steer_sweep"), ("combined", COMBINED, "steer_combined")]
)
async def test_each_route_files_first_then_one_call_with_the_id(
    which: str, path: str, action: str
) -> None:
    async with Session() as s:
        first = await _call(s, which)
        filed = s.log("miworkbench", "POST", FILE)
        assert len(filed) == 1 and filed[0].body["tool_name"] == action
        assert (
            filed[0].body["payload"]["_route"] == path
            and filed[0].body["payload"]["_method"] == "POST"
        )
        assert s.log("miworkbench", "POST", path) == []
        await _call(s, which)  # repeat while pending: nothing new
        assert (
            len(s.log("miworkbench", "POST", FILE)) == 1
            and s.log("miworkbench", "POST", path) == []
        )
        s.s.approve()
        await _call(s, which)  # repeat AFTER approval, without the id: nothing new filed
        assert (
            len(s.log("miworkbench", "POST", FILE)) == 1
        ), "a second approval after the first was approved"
        calls = s.log("miworkbench", "POST", path)
        approval_id = first.structured_content["approval"]["id"]
        assert len(calls) == 1 and calls[0].headers["x-mistudio-approval-request"] == approval_id
