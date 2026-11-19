"""``Route.computes_only``: a POST read that only computes (PADR R2M-4; OVN-miassist-pb003-3).

R1 review fix (OR1-pb-12), 2026-11-16. The flag is the only thing that lets an unmarked POST on
miServer or miDataworks register as a read, so it is never trusted on its own: the registration rules
are pinned here, and the set of flagged routes must equal ``REVIEWED``, a literal list in which each
route cites the app code that shows it writes nothing. A route flagged without review, or a reviewed
route that lost its flag, goes red.
"""

from __future__ import annotations

import dataclasses

import pytest

from miassist.adapters.base import GateClass, ProgrammingError, Route
from miassist.adapters.routes import ROUTES, check_registration
from tests.support.response_shapes import snapshot

#: Every computes-only route, with the app code that shows it computes and writes nothing.
#: 004's three POST reads added at the merge (integration, from the 004/005 fixer's NEEDS.md; each
#: re-read at the snapshot commit: the cited files are unchanged 58087b1..dcec0cb). Re-read at
#: 498efcf2 (the 021-P3 re-vendor, 2026-11-17): operators.py and build_plan_service.py are unchanged
#: since d4c790e7; recipes.py's validate moved one line and versions.py's plan_build six lines, both
#: bodies unchanged. Re-read at f6d6b98c and 06ab2ee30 (the final re-vendor, 2026-11-17): the four
#: cited miDataworks files are unchanged 498efcf2..f6d6b98c; miWorkbench's probe_monitors.py is
#: unchanged above line 1665 (one import line) and the three forecast services are unchanged.
REVIEWED: dict[str, str] = {
    "midataworks.validate_operator": (
        "miDataworks f6d6b98c backend/src/api/v1/endpoints/operators.py:305-325 validate_params: "
        "require_allowed + require_valid_params (+ the designer worker's template check) and "
        "returns {valid, ...}; no db session, no job, no write."
    ),
    "midataworks.validate_recipe": (
        "miDataworks f6d6b98c backend/src/api/v1/endpoints/recipes.py:142 validate "
        "(response_model=ValidationOut): validates a recipe body against the operator registry; "
        "no row, no job."
    ),
    "midataworks.plan_version": (
        "miDataworks f6d6b98c backend/src/api/v1/endpoints/versions.py:70-85 plan_build, docstring "
        "'Writes nothing; never gated'; services/build_plan_service.py:141-215 returns "
        "out['writes'] = 'nothing: no job, no ledger row, no version'."
    ),
    "miworkbench.dp_run_forecast": (
        "miWorkbench 06ab2ee30 backend/src/api/v1/endpoints/probe_monitors.py:776-813 "
        "forecast_probe_run: 'No GPU, no row, no task'; it SELECTs the model and the view, "
        "runs forecast_for_request / time_forecast_for_request / recommendation_for, and returns; "
        "no db.add, commit or dispatch."
    ),
}

READ_POST = Route(
    id="miworkbench.test_compute",
    app="miworkbench",
    method="POST",
    path="/api/v1/probe-monitors/runs/forecast",
    gate=GateClass.READ,
    purpose="test",
    computes_only=True,
)


def test_the_flagged_routes_are_exactly_the_reviewed_ones() -> None:
    assert {r.id for r in ROUTES if r.computes_only} == set(REVIEWED)


@pytest.mark.parametrize("route_id", sorted(REVIEWED))
def test_a_reviewed_route_is_an_ungated_post_in_the_app(route_id: str) -> None:
    """The app's own route agrees: a POST that carries no approval marker (a gated or conditional
    route is never a computation), at the reviewed commit."""
    route = ROUTES.get(route_id)
    assert route.method == "POST" and route.gate is GateClass.READ
    index = snapshot(route.app)
    op = index["paths"][route.path]["post"]
    assert "x-approval-action" not in op and "x-approval-when" not in op
    assert index["commit"] in REVIEWED[route_id]


def test_computes_only_is_accepted_on_a_post_read() -> None:
    check_registration(READ_POST)


@pytest.mark.parametrize(
    "change",
    [
        {"gate": GateClass.APP_GATED},
        {"gate": GateClass.UNGATED_WRITE, "floor_entry": "detector.create_behaviour"},
        {"method": "GET"},
        {"method": "PUT"},
    ],
    ids=["app_gated", "ungated_write", "get", "put"],
)
def test_computes_only_is_refused_anywhere_but_a_post_read(change: dict[str, object]) -> None:
    with pytest.raises(ProgrammingError, match="computes-only"):
        check_registration(dataclasses.replace(READ_POST, **change))


def test_a_non_get_read_without_a_reason_is_refused() -> None:
    with pytest.raises(ProgrammingError, match="must say why"):
        check_registration(dataclasses.replace(READ_POST, computes_only=False))
