"""R2M-14, R3M-3, R3M-4: the guarded list is derived per route from the vendored vectors, and,
independently, holds literals written here."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from miassist_eval import classes, gpu_guard, openapi_ref
from tests.support import harness

#: Written here by hand, never read from the vectors file (R3M-3): round 1's labelling routes (one
#: shared action, three routes) and the goals' GPU routes.
LITERALS = [
    ("POST", "/api/v1/labeling"),
    ("POST", "/api/v1/labeling/panel"),
    ("POST", "/api/v1/extractions/{extraction_id}/label"),
    ("POST", "/api/v1/probe-monitors/runs"),
    ("POST", "/api/v1/probe-monitors/probes/{probe_id}/evaluate"),
    ("POST", "/api/v1/probe-monitors/probes/{probe_id}/definition"),
    ("POST", "/api/v1/probe-monitors/judge-prompts/try"),
]
#: Literals whose vectors are not vendored yet (OVN-miassist-eval-10): 044's route skips LOUDLY
#: until Core re-vendors, and fails under MIASSIST_REQUIRE_CORE=1 (it is not in the reference
#: either, so a request to it is ``unknown_route`` meanwhile).
PENDING_VENDORING = [
    (("POST", "/api/v1/wsp/captures"), "044's vectors"),
]
#: The steering GPU starts, written here by hand (R1 review fix OR1-002-4, 2026-11-16; ``combined``
#: was missing, and the synchronous routes were in neither list). Each must be guarded by the
#: derived list OR refused on the miAssist surface with ``gpu_list_incomplete``: never pass, never
#: skip.
STEERING_LITERALS = [
    ("POST", "/api/v1/steering/async/compare"),
    ("POST", "/api/v1/steering/async/sweep"),
    ("POST", "/api/v1/steering/async/combined"),
    ("POST", "/api/v1/steering/compare"),
    ("POST", "/api/v1/steering/sweep"),
]


def vectors() -> list[dict]:
    return json.loads(gpu_guard.vectors_path().read_text())["vectors"]


def test_guarded_set_equals_the_vectors_route_for_route() -> None:
    """Independent of ``openapi_ref.resolve`` (R1 review fix OR1-002-10, 2026-11-16): the expected
    keys are each vector's OWN ``route`` template, compared with what the guard derived from the
    request path; the guard and the expectation no longer share one resolver."""
    expected = {(str(v["method"]).upper(), str(v["route"])) for v in vectors()}
    assert len(expected) == len(vectors())
    assert set(harness.gpu_list()) == expected
    assert len(harness.gpu_list()) == len(vectors()), "two vectors collapsed into one guard key"


@pytest.mark.parametrize(("method", "template"), LITERALS)
def test_literal_route_is_guarded(method: str, template: str) -> None:
    assert (method, template) in harness.gpu_list(), f"{method} {template} is not guarded"


def test_the_three_labelling_routes_share_one_action() -> None:
    gpu = harness.gpu_list()
    actions = {gpu[k].action for k in LITERALS[:3]}
    assert actions == {"start_labeling"}


@pytest.mark.parametrize(("key", "source"), PENDING_VENDORING)
def test_pending_literal_is_guarded_once_vendored(key: tuple[str, str], source: str) -> None:
    if key in harness.gpu_list():
        return
    message = f"{key[0]} {key[1]} is not guarded: {source} are not vendored yet (Core 001-V)"
    if os.environ.get("MIASSIST_REQUIRE_CORE") == "1":
        pytest.fail(message)
    pytest.skip(f"LOUD SKIP: {message}")


@pytest.mark.parametrize(("method", "template"), STEERING_LITERALS)
def test_a_steering_start_is_guarded_or_refused_never_passed(method: str, template: str) -> None:
    wb = harness.refs()["miworkbench"]
    route = openapi_ref.resolve(wb, method, template.replace("{", "").replace("}", ""))
    assert route is not None and route.template == template, f"{template} left the reference"
    edge = harness.edge()
    verdict = edge.check("miworkbench", method, template, {}, harness.HEADERS["miworkbench"], {})[1]
    assert verdict is not None, f"{method} {template} passed ungated on the miAssist surface"
    if (method, template) in harness.gpu_list():
        assert verdict.cls == classes.UNGATED_GPU_START
    else:
        assert verdict.cls == classes.GPU_LIST_INCOMPLETE


def test_the_incomplete_list_is_derived_from_the_reference_and_the_vectors() -> None:
    """Every steering start in the reference is in ``incomplete`` exactly when no vector holds it."""
    wb = harness.refs()["miworkbench"]
    gpu = harness.gpu_list()
    missing = gpu_guard.incomplete(gpu, wb)
    assert set(missing) == {f"{m} {t}" for m, t in STEERING_LITERALS if (m, t) not in gpu}
    held = dict(gpu)
    for m, t in STEERING_LITERALS:
        held[(m, t)] = gpu_guard.GpuStart("x", t, m)
    assert gpu_guard.incomplete(held, wb) == [], "the refusal must lift once the vectors hold it"


def test_a_vendored_steering_route_lifts_its_refusal() -> None:
    gpu = dict(harness.gpu_list())
    key = ("POST", "/api/v1/steering/async/compare")
    gpu[key] = gpu_guard.GpuStart("steer_compare", key[1], key[0])
    from miassist_eval.edge import Edge

    edge = Edge(surface="miassist", refs=harness.refs(), profiles=harness.profiles(), gpu=gpu)
    verdict = edge.check("miworkbench", *key, {}, harness.HEADERS["miworkbench"], {})[1]
    assert verdict is not None and verdict.cls == classes.UNGATED_GPU_START


@pytest.mark.parametrize("playbook", ["steering"])
def test_a_goal_with_an_unguarded_gpu_start_is_refused_on_the_miassist_surface(
    playbook: str, vectors_without_steering: Path
) -> None:
    """Against vectors without the steering rows (the refusal's own premise; OVN-miassist-int-5)."""
    gpu = harness.gpu_list.__wrapped__()  # uncached: the fixture's file
    assert gpu_guard.goal_incomplete(playbook, gpu), "the fixture still holds steering rows"
    with pytest.raises(classes.Refusal) as caught:
        gpu_guard.refuse_incomplete_goal(playbook, gpu, "miassist")
    assert caught.value.cls == classes.GPU_LIST_INCOMPLETE
    gpu_guard.refuse_incomplete_goal(playbook, gpu, "baseline")  # the baseline holds instead


#: Integration (OVN-miassist-int-5), 2026-11-16: what Core's vendored vectors (045-A0 @ fdb53989a)
#: cover, written by hand. The three ``/async/`` starts are guarded (an approved id is required);
#: the synchronous ``/compare`` and ``/sweep`` have no vector and stay REFUSED on the miAssist surface.
STEERING_COVERED = STEERING_LITERALS[:3]
STEERING_UNCOVERED = STEERING_LITERALS[3:]


def test_the_vendored_vectors_lift_the_steering_refusal_route_by_route() -> None:
    gpu = harness.gpu_list()
    edge = harness.edge()
    for method, template in STEERING_COVERED:
        assert (method, template) in gpu, f"{template} is not covered by the vendored vectors"
        assert gpu[(method, template)].action == "steer_" + template.rsplit("/", 1)[1]
        verdict = edge.check(
            "miworkbench", method, template, {}, harness.HEADERS["miworkbench"], {}
        )
        assert verdict[1] is not None and verdict[1].cls == classes.UNGATED_GPU_START
    for method, template in STEERING_UNCOVERED:
        assert (method, template) not in gpu, f"{template} gained a vector: review its refusal"
        verdict = edge.check(
            "miworkbench", method, template, {}, harness.HEADERS["miworkbench"], {}
        )
        assert verdict[1] is not None and verdict[1].cls == classes.GPU_LIST_INCOMPLETE
    assert gpu_guard.goal_incomplete("steering", gpu) == []
    gpu_guard.refuse_incomplete_goal("steering", gpu, "miassist")  # lifted: no refusal


def test_every_goal_names_a_playbook_with_listed_gpu_routes() -> None:
    from miassist_eval import goals

    for goal in goals.load().raw["goals"]:
        assert goal["playbook_id"] in gpu_guard.GOAL_GPU_ROUTES, goal["id"]
    for playbook in ("dataset", "detector-probe"):
        assert gpu_guard.goal_incomplete(playbook, harness.gpu_list()) == [], playbook
    assert gpu_guard.goal_incomplete("not-a-playbook", harness.gpu_list()) != []


def test_baseline_steering_start_is_a_gpu_start_held_by_the_operator(tmp_path: Path) -> None:
    from miassist_eval import recorder

    key = ("POST", "/api/v1/steering/async/combined")
    replay_edge = harness.edge("baseline")
    assert replay_edge.check("miworkbench", *key, {}, {}, {})[1] is None  # replay: no GPU
    held = harness.edge("baseline", hold=recorder.tty_hold(str(tmp_path / "no-tty")))
    verdict = held.check("miworkbench", *key, {}, {}, {})[1]
    assert verdict is not None and verdict.cls == classes.UNGATED_GPU_START


def test_every_arm_key_is_a_vector_route() -> None:
    gpu = harness.gpu_list()
    arms = harness.profiles()["miworkbench"]["gpu_arms"]
    for key in arms:
        method, template = key.split(" ", 1)
        assert (method, template) in gpu, key
        assert gpu[(method, template)].arm is not None


def test_an_arm_on_no_vector_route_is_a_load_error() -> None:
    arms = {"POST /api/v1/not-a-gpu-route": {"from": "query.x", "parse": "fastapi_bool"}}
    with pytest.raises(ValueError, match="no vector"):
        gpu_guard.load(harness.refs()["miworkbench"], arms)


@pytest.mark.parametrize("surface", ["miassist", "baseline"])
def test_missing_vectors_file_refuses_on_both_surfaces(
    tmp_path: Path, surface: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MIASSIST_WB_PAYLOAD_VECTORS", str(tmp_path / "absent.json"))
    with pytest.raises(classes.Refusal) as caught:
        gpu_guard.load(harness.refs()["miworkbench"], {})
    assert caught.value.cls == classes.GPU_LIST_MISSING


def test_an_empty_vectors_file_refuses(tmp_path: Path) -> None:
    path = tmp_path / "v.json"
    path.write_text(json.dumps({"vectors": []}))
    with pytest.raises(classes.Refusal) as caught:
        gpu_guard.load(harness.refs()["miworkbench"], {}, path)
    assert caught.value.cls == classes.GPU_LIST_MISSING


def test_dropping_one_vector_drops_its_literal(tmp_path: Path) -> None:
    """The literal check is independent of the file: a copy without labeling/panel loses it."""
    doc = json.loads(gpu_guard.vectors_path().read_text())
    doc["vectors"] = [v for v in doc["vectors"] if v["route"] != "/api/v1/labeling/panel"]
    path = tmp_path / "v.json"
    path.write_text(json.dumps(doc))
    gpu = gpu_guard.load(harness.refs()["miworkbench"], {}, path)
    assert ("POST", "/api/v1/labeling/panel") not in gpu
