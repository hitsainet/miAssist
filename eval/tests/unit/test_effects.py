"""FR-002.25, FR-002.26: milestones in order with ``after``; overlapping waits; polls."""

from __future__ import annotations

from miassist_eval import effects, goals
from tests.support import harness


def line(t, app, method, route, status, answer=None, path=None, **kw):
    return {
        "t_mono": t,
        "app": app,
        "method": method,
        "route": route,
        "path": path or route,
        "status": status,
        "answer": answer,
        **kw,
    }


def test_milestones_in_order_and_after_is_honoured() -> None:
    g = goals.load().goal("detector-refund")
    log = [
        line(
            1,
            "miworkbench",
            "GET",
            "/api/v1/probe-monitors/probes/{probe_id}",
            200,
            {"rung_language": "rung 2"},
        ),  # before trained: does not count
        line(2, "miworkbench", "POST", "/api/v1/probe-monitors/datasets", 201, {}),
        line(
            3,
            "miworkbench",
            "GET",
            "/api/v1/probe-monitors/runs/{run_id}",
            200,
            {"status": "running"},
        ),
        line(
            4,
            "miworkbench",
            "GET",
            "/api/v1/probe-monitors/runs/{run_id}",
            200,
            {"status": "completed"},
        ),
        line(
            5,
            "miworkbench",
            "GET",
            "/api/v1/probe-monitors/probes/{probe_id}",
            200,
            {"rung_language": "rung 2"},
        ),
    ]
    assert effects.milestones(log, g) == [("data_ready", 2.0), ("trained", 4.0), ("evaluated", 5.0)]


def test_exported_through_either_route() -> None:
    g = goals.load().goal("tone-warmer")
    a = [line(1, "miworkbench", "POST", "/api/v1/cluster-profiles/export-bundle", 200, {})]
    b = [line(1, "miworkbench", "GET", "/api/v1/cluster-profiles/{profile_id}/export", 200, {})]
    assert effects.milestones(a, g) == effects.milestones(b, g) == [("exported", 1.0)]


def test_an_import_with_activate_true_is_not_imported() -> None:
    g = goals.load().goal("tone-warmer")
    log = [line(1, "miserver", "POST", "/api/clusters/import", 200, {}, query={"activate": "true"})]
    assert effects.milestones(log, g) == []


def test_overlapping_gpu_and_approval_waits_give_the_expected_active_time() -> None:
    profiles = harness.profiles()
    log = [
        line(
            10,
            "midataworks",
            "GET",
            "/api/v1/approvals/{approval_id}",
            200,
            {"status": "pending"},
            path="/api/v1/approvals/a1",
        ),
        line(
            20,
            "midataworks",
            "GET",
            "/api/v1/jobs/{job_id}",
            200,
            {"status": "running"},
            path="/api/v1/jobs/j1",
        ),
        line(
            40,
            "midataworks",
            "GET",
            "/api/v1/approvals/{approval_id}",
            200,
            {"status": "executed"},
            path="/api/v1/approvals/a1",
        ),
        line(
            70,
            "midataworks",
            "GET",
            "/api/v1/jobs/{job_id}",
            200,
            {"status": "completed"},
            path="/api/v1/jobs/j1",
        ),
    ]
    w = effects.waits(log, profiles, end=100)
    assert sorted((k, s, e) for k, s, e in w) == [("approval", 10, 40), ("gpu", 20, 70)]
    assert effects.active_time(0, 100, w) == 100 - 60  # merged [10, 70]


def test_an_open_wait_runs_to_the_end() -> None:
    log = [
        line(
            5,
            "midataworks",
            "GET",
            "/api/v1/jobs/{job_id}",
            200,
            {"status": "queued"},
            path="/api/v1/jobs/j1",
        )
    ]
    assert effects.waits(log, harness.profiles(), end=50) == [("gpu", 5, 50)]


def test_handoff_waits_run_from_refusal_to_done() -> None:
    log = [
        line(
            3, "miserver", "POST", "/api/probes/{probe_id}/arm", 403, {}, refused="operator_handoff"
        ),
        {"t_mono": 9, "app": "miserver", "handoff_done": True},
    ]
    assert effects.waits(log, harness.profiles(), end=20) == [("handoff", 3, 9)]


def test_poll_calls_during_open_waits() -> None:
    profiles = harness.profiles()
    eff = [
        line(
            11,
            "midataworks",
            "GET",
            "/api/v1/jobs/{job_id}",
            200,
            {"status": "running"},
            path="/api/v1/jobs/j1",
        ),
        line(21, "midataworks", "POST", "/api/v1/versions", 202, {}),
    ]
    tap = [
        {"method": "tools/call", "t_mono": 10, "t_answer": 12},
        {"method": "tools/call", "t_mono": 20, "t_answer": 22},
    ]
    w = [("gpu", 5, 30)]
    assert effects.poll_calls(tap, eff, profiles, w) == 1


def test_a_refused_line_is_never_a_milestone_even_when_its_predicate_holds() -> None:
    """R1 review fix (OR1-002-10), 2026-11-16: RH1 survived because every goal predicate names a 2xx
    status. A predicate without one (a ``nonempty`` check only) would match a refused line's body;
    the refusal must still keep it from counting."""
    goal = {
        "milestones": [
            {
                "id": "seen",
                "any_of": [
                    {
                        "app": "midataworks",
                        "method": "POST",
                        "route": "/api/v1/publishes",
                        "predicate": {"nonempty": ["refused"]},
                    }
                ],
            }
        ]
    }
    refused = line(
        1,
        "midataworks",
        "POST",
        "/api/v1/publishes",
        403,
        {"refused": "agent_attempted_decision"},
        refused="agent_attempted_decision",
    )
    assert effects.milestones([refused], goal) == []
    assert effects.milestones([{**refused, "refused": None}], goal) == [("seen", 1.0)]
