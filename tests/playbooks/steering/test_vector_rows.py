"""Each steering filing on the PRODUCTION registry is 045's published vector for its own route
(005 FTASKS 3.3 and 4.2; FPRD FR-005.15, A38): row 31 for the sweep, row 32 for the combined run.

ENH-012 acceptance (review/enh012-acceptance, 2026-11-26). 3.3 and 4.2 stayed ``[?]`` on "the
filing equals 045's vector for row 31 / row 32": the per-route test checked ``_route`` and
``_method`` only, and Core's ``test_canonical_payload`` reproduces each vector through
``canonical_payload`` without the playbook. Here the playbook files, the operator approves, and
the one call that spends the approval is compared with the filing by 045's rule:

- the filed ``tool_name`` and ``_route``/``_method`` are the vector row's ``action`` and route;
- every key the vector's request body carries (the route's required fields) is filed;
- the filing equals ``canonical_payload`` of the call's own body, so miWorkbench's gate, which
  recomputes it from the call, finds the approved payload (045 FR-13);
- the vector row reproduces through Core's rule (one row per route, the payload names its route,
  so an approval for one route cannot be spent on the other).
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from miassist.adapters.miworkbench import canonical_payload
from miassist.adapters.routes import ROUTES
from tests.playbooks.steering import support
from tests.playbooks.steering.support import Session
from tests.support.vectors import VECTORS_FILE

FILE = "/api/v1/mcp/approvals"
TWO = [{"feature": "evalfx-feat-1", "strength": 1.0}, {"feature": "evalfx-feat-2", "strength": 0.5}]
ROWS = {"sweep": "31", "combined": "32"}


@pytest.fixture(autouse=True)
def production_registry(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(support, "gpu_registry", lambda: ROUTES)


def vector(row: str) -> dict[str, Any]:
    (found,) = [v for v in json.loads(VECTORS_FILE.read_text())["vectors"] if v["row"] == row]
    return found


async def _call(s: Session, which: str, **kw: Any) -> Any:
    if which == "sweep":
        return await s.call(
            "miassist_steering_try", {"feature": "evalfx-feat-1", "prompt": "Hi.", **kw}
        )
    return await s.call(
        "miassist_steering_save", {"name": "pair", "features": TWO, "prompt": "Hi.", **kw}
    )


@pytest.mark.parametrize("which", ["sweep", "combined"])
def test_the_vector_row_names_its_route_and_reproduces(which: str) -> None:
    v = vector(ROWS[which])
    route = ROUTES.get(f"miworkbench.steer_{which}")
    assert (v["action"], v["method"], v["route"]) == (route.approval_action, "POST", route.path)
    request = v["request"]
    assert canonical_payload(v["method"], v["route"], {}, request["query"], request["body"]) == (
        v["payload"]
    )


@pytest.mark.parametrize("which", ["sweep", "combined"])
async def test_each_filing_is_its_rows_vector_and_the_call_spends_exactly_it(which: str) -> None:
    v = vector(ROWS[which])
    async with Session() as s:
        first = await _call(s, which)
        (filed,) = s.log("miworkbench", "POST", FILE)
        s.s.approve()
        await _call(s, which, approval_id=first.structured_content["approval"]["id"])
        (call,) = s.log("miworkbench", "POST", v["route"])
    payload = filed.body["payload"]
    assert filed.body["tool_name"] == v["action"]
    assert (payload["_method"], payload["_route"]) == (v["payload"]["_method"], v["route"])
    missing = set(v["request"]["body"]) - set(payload)
    assert not missing, f"the filing lacks the vector's required fields {sorted(missing)}"
    assert payload == canonical_payload("POST", v["route"], {}, {}, call.body)
