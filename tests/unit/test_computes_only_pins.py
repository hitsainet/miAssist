"""``Route.computes_only`` is a claim that a POST writes nothing; it is pinned, never trusted
(R1 review fix OR1-pb-12, 2026-11-16; controls P06, P07 and N17 survived in round 1).

- ``check_registration`` refuses the flag on anything but a POST read, and refuses a non-GET read
  without the flag or gate machinery (the registration rule itself, with its wiring);
- the live registry's computes-only routes equal a LITERAL list, each with the app-side citation
  that the route writes nothing. A new computes-only route fails here until someone cites its code.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from miassist.adapters.base import GateClass, ProgrammingError, Route
from miassist.adapters.routes import ROUTES, RouteRegistry, check_registration

#: Each computes-only route and where its app says it writes nothing (004's three; 003 adds its
#: training forecast at merge: probe_monitors forecast, "CPU only, writes nothing").
COMPUTES_ONLY = {
    "midataworks.validate_operator": "operators.py:305-323 validate_params: returns a verdict",
    "midataworks.validate_recipe": "recipes.py:141 validate, response_model=ValidationOut",
    "midataworks.plan_version": "versions.py:64-79 'Writes nothing; never gated'",
    # 003's training forecast, added at the merge (integration; the full citation is in
    # tests/contract/test_computes_only.py::REVIEWED)
    "miworkbench.dp_run_forecast": "probe_monitors.py:776-813 'No GPU, no row, no task'",
}

BASE = Route(
    id="midataworks.evalfx_probe",
    app="midataworks",
    method="POST",
    path="/api/v1/evalfx",
    gate=GateClass.READ,
    purpose="test",
    computes_only=True,
)


def test_the_live_registry_marks_exactly_the_cited_routes() -> None:
    marked = {r.id for r in ROUTES if r.computes_only}
    assert marked == set(COMPUTES_ONLY), marked ^ set(COMPUTES_ONLY)


def test_a_post_read_with_the_flag_registers() -> None:
    check_registration(BASE)
    assert BASE in RouteRegistry((BASE,))


@pytest.mark.parametrize(
    "bad",
    [
        replace(BASE, method="GET"),
        replace(BASE, gate=GateClass.APP_GATED),
        replace(BASE, gate=GateClass.UNGATED_WRITE, floor_entry=None),
    ],
)
def test_the_flag_on_anything_but_a_post_read_is_refused(bad: Route) -> None:
    with pytest.raises(ProgrammingError):
        check_registration(bad)
    with pytest.raises(ProgrammingError):
        RouteRegistry((bad,))


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
def test_a_non_get_read_must_say_why(method: str) -> None:
    with pytest.raises(ProgrammingError, match="must say why"):
        check_registration(replace(BASE, method=method, computes_only=False))
    with pytest.raises(ProgrammingError, match="must say why"):
        RouteRegistry((replace(BASE, method=method, computes_only=False),))
