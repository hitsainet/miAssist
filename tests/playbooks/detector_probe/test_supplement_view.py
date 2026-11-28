"""miWorkbench's ``supplement`` views never stand in for a detector view (train A1, 2026-11-25).

miWorkbench 15781e7e9 (ENH-010 FU-7a C2, train W1) adds ``supplement`` to ``DatasetRole``
(``schemas/probe_monitor.py:84``): extra practice rows for a WSP bundle, negatives only,
"measured on and never fitted on", which "never counts towards a rung". A behaviour's views can
now include one. The detector playbook keys views by role (``snapshot.role_of``), so a supplement
view is held under its own role: it never fills a required role (``flow.REQUIRED_ROLES``), and it
is never in the evaluation the verdict files (``defaults.EVAL_ROLES``). The fake answers it in
miWorkbench's pinned shape, so against a pin before 15781e7e9 the role is refused at teardown.
"""

from __future__ import annotations

from tests.playbooks.detector_probe.fakes import KEY, PM, World
from tests.playbooks.detector_probe.journey import journey
from tests.playbooks.detector_probe.test_train_verdict import filings, trained, world_with_views
from tests.support import response_shapes as rs

SUPPLEMENT = {
    "id": "evalfx-view-supplement",
    "role": "supplement",
    "distribution": None,
    "behaviour": KEY,
    "counts": {"positive": 0, "negative": 400},
}


def with_supplement(world: World) -> World:
    world.views.append(dict(SUPPLEMENT))
    return world


def test_the_pinned_shapes_carry_supplement() -> None:
    """The behaviour detail's views (a hand-derived shape whose role enum is ``DatasetRole``) and
    the dataset registration's request both name the role."""
    detail = rs.schema_for("miworkbench", "GET", f"{PM}/behaviours/{{key}}", 200)
    role = rs.at(detail, "adopted", "views", "[]", "role")
    assert rs.check(role, "supplement") == [] and rs.check(role, "practice") != []
    body = rs.snapshot("miworkbench")["paths"][f"{PM}/datasets"]["post"]["requestBody"]
    assert (
        "supplement" in body["content"]["application/json"]["schema"]["properties"]["role"]["enum"]
    )


def test_a_supplement_view_is_never_evaluated() -> None:
    world = with_supplement(trained(world_with_views()))
    with journey(world=world) as j:
        first = j.data("miassist_detector_verdict", {"key": KEY})
        filed = filings(j)[0].body
    assert first["approval"]["decide_in"] == "miworkbench"
    assert filed["payload"]["dataset_ids"] == ["evalfx-view-1", "evalfx-view-3", "evalfx-view-4"]


def without_calibration() -> World:
    world = world_with_views()
    world.views = [v for v in world.views if v["role"] != "calibration"]
    return world


def test_a_supplement_view_fills_no_required_role() -> None:
    """Without its calibration view the behaviour is not views-ready, supplement or not: the same
    state, the same views, the supplement held under its own role."""
    with journey(world=without_calibration()) as j:
        plain = j.data("miassist_detector_data", {"key": KEY})["data"]
    with journey(world=with_supplement(without_calibration())) as j:
        doc = j.data("miassist_detector_data", {"key": KEY})["data"]
    assert plain["state"] != "views_ready" and doc["state"] == plain["state"], doc["state"]
    assert doc["views"].pop("supplement")["id"] == SUPPLEMENT["id"]
    assert doc["views"] == plain["views"] and "calibration" not in doc["views"]
