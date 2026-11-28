"""005 against the apps' REAL answers (R1 review fixes OR1-pb-2 to OR1-pb-5, OR1-pb-9, OR1-pb-15,
OR1-pb-16; 2026-11-16). The fakes answer from miWorkbench's and miServer's own response shapes."""

from __future__ import annotations

from typing import Any

import pytest

from tests.playbooks.steering.fake import RESULT, Steering
from tests.playbooks.steering.support import Session, data
from tests.support import shapes

SWEEP = "/api/v1/steering/async/sweep"
COMBINED = "/api/v1/steering/async/combined"
FILE = "/api/v1/mcp/approvals"
RESULT_PATH = RESULT.split(" ", 1)[1]
TWO = [
    {"feature": "evalfx-feat-1", "strength": 1.0},
    {"feature": "evalfx-feat-2", "strength": 0.5},
]


async def try_(s: Session, **kw: Any) -> Any:
    return await s.call(
        "miassist_steering_try", {"feature": "evalfx-feat-1", "prompt": "Tell me.", **kw}
    )


async def approved_try(s: Session) -> Any:
    first = await try_(s)
    s.s.approve()
    return await try_(s, approval_id=first.structured_content["approval"]["id"])


# -- OR1-pb-2: the task status is an object -----------------------------------------------------


async def test_a_task_that_runs_then_finishes_is_polled_to_its_result() -> None:
    async with Session(Steering(task_states=["pending", "started", "progress", "success"])) as s:
        got = data(await approved_try(s))
    assert got["state"] == "swept" and got["usable_strength"] is not None
    assert len(s.log("miworkbench", "GET", RESULT_PATH)) == 4


async def test_a_running_task_reads_as_running_then_as_its_result() -> None:
    st_ = Steering(task_states=["progress"] * 1000)
    async with Session(st_) as s:
        running = await approved_try(s)
        got = data(running)
        assert got["state"] == "sweeping" and got["swept"] is False
        assert "results" not in got and got["waiting"][0]["kind"] == "gpu"
        task_id = got["task_id"]
        nxt = running.structured_content["next_steps"][0]
        assert nxt["args"]["task_id"] == task_id
        st_.task_states = ["success"]
        st_.tasks[task_id]["reads"] = 0
        done = data(await try_(s, task_id=task_id))
    assert done["state"] == "swept" and done["results"]
    assert len(s.log("miworkbench", "POST", SWEEP)) == 1


async def test_a_task_that_fails_reads_as_failed_with_its_error() -> None:
    async with Session(Steering(task_states=["progress", "failure"])) as s:
        result = await approved_try(s)
    assert result.is_error and result.content[0].text.startswith("sweep_failed:")
    assert "CUDA out of memory" in result.content[0].text


@pytest.mark.parametrize("status", ["success", {"state": "success"}, {"status": "finished"}, None])
async def test_an_unknown_status_shape_fails_closed(status: Any) -> None:
    """A string, a foreign object, a status outside the enum, or none: never a finished task."""
    st_ = Steering()
    async with Session(st_) as s:
        # a full, valid sweep result beside the foreign status: only the status may refuse it
        s.wb.on("GET", RESULT_PATH, lambda r: {**st_.result(r), "status": status})
        result = await approved_try(s)
    assert result.is_error and result.content[0].text.startswith("task_unreadable:")
    assert shapes.collected()  # deliberately not miWorkbench's shape


async def test_a_combined_task_that_runs_then_fails_saves_nothing() -> None:
    async with Session(Steering(task_states=["progress", "failure"])) as s:
        first = await s.call(
            "miassist_steering_save", {"name": "p", "features": TWO, "prompt": "Hi"}
        )
        s.s.approve()
        done = await s.call(
            "miassist_steering_save",
            {
                "name": "p",
                "features": TWO,
                "prompt": "Hi",
                "approval_id": first.structured_content["approval"]["id"],
            },
        )
    assert done.is_error and done.content[0].text.startswith("combined_failed:")
    assert s.log("miworkbench", "POST", "/api/v1/cluster-profiles") == []


# -- OR1-pb-3 and OR1-pb-16: combined_output, and the features it applied ------------------------


async def save_two(st_: Steering) -> tuple[Session, Any]:
    s = Session(st_)
    async with s:
        first = await s.call(
            "miassist_steering_save", {"name": "p", "features": TWO, "prompt": "Hi"}
        )
        s.s.approve()
        done = await s.call(
            "miassist_steering_save",
            {
                "name": "p",
                "features": TWO,
                "prompt": "Hi",
                "approval_id": first.structured_content["approval"]["id"],
            },
        )
    return s, done


async def test_the_combined_check_reads_combined_output() -> None:
    s, done = await save_two(Steering())
    got = data(done)
    assert got["state"] == "saved" and got["combined_check"]["fluent"] is True
    assert len(s.log("miworkbench", "POST", "/api/v1/cluster-profiles")) == 1


@pytest.mark.parametrize(
    "applied",
    [
        [{"feature_idx": 42, "layer": 6, "strength": 1.0}],
        [
            {"feature_idx": 42, "layer": 6, "strength": 1.0},
            {"feature_idx": 99, "layer": 6, "strength": 0.5},
        ],
        [
            {"feature_idx": 42, "layer": 6, "strength": 1.0},
            {"feature_idx": 7, "layer": 6, "strength": 2.0},
        ],
    ],
)
async def test_a_task_that_steered_other_features_is_not_this_clusters_check(
    applied: list[dict[str, Any]],
) -> None:
    s, done = await save_two(Steering(applied_override=applied))
    assert done.is_error and done.content[0].text.startswith("combined_mismatch:")
    assert s.log("miworkbench", "POST", "/api/v1/cluster-profiles") == []


# -- OR1-pb-15: save's combined check without the GPU rows -------------------------------------


async def test_save_two_without_the_gpu_rows_is_a_calm_refusal() -> None:
    async with Session(gpu=False) as s:
        result = await s.call(
            "miassist_steering_save", {"name": "p", "features": TWO, "prompt": "Hi"}
        )
    assert result.is_error and result.content[0].text.startswith("steering_gate_not_ready:")
    assert s.log("miworkbench", "POST", FILE) == []
    assert s.log("miworkbench", "POST", COMBINED) == []
    assert s.log("miworkbench", "POST", "/api/v1/cluster-profiles") == []


# -- OR1-pb-4: serve reads miServer's import answer, its models and its health ----------------


async def saved(s: Session) -> str:
    result = await s.call(
        "miassist_steering_save",
        {"name": "sunny", "features": [{"feature": "evalfx-feat-1", "strength": 1.0}]},
    )
    return str(data(result)["profile_id"])


async def test_a_resident_model_gets_no_load_approval() -> None:
    async with Session(Steering(model_status="loaded")) as s:
        got = data(await s.call("miassist_steering_serve", {"cluster": await saved(s)}))
    assert got["state"] in ("awaiting_activation", "imported")
    assert s.log("miserver", "POST", "/api/models/{model_id}/load") == []
    assert s.sv.calls("GET", "/api/models")


async def test_a_downloaded_model_not_resident_is_loaded_by_its_integer_id() -> None:
    async with Session(Steering(model_status="ready")) as s:
        result = await s.call("miassist_steering_serve", {"cluster": await saved(s)})
        again = await s.call("miassist_steering_serve", {"cluster": await saved(s)})
    assert data(result)["state"] == "model_load_waiting"
    assert data(again)["state"] == "model_load_waiting"
    loads = s.log("miserver", "POST", "/api/models/{model_id}/load")
    assert [r.path for r in loads] == ["/api/models/3/load"]
    assert s.log("miserver", "POST", "/v1/chat/completions") == []


async def test_no_downloaded_model_refuses_and_files_nothing() -> None:
    async with Session(Steering(model_status=None)) as s:
        result = await s.call("miassist_steering_serve", {"cluster": await saved(s), "prompt": "x"})
    assert result.is_error and result.content[0].text.startswith("model_not_downloaded:")
    assert s.log("miserver", "POST", "/api/models/{model_id}/load") == []
    assert s.log("miserver", "POST", "/v1/chat/completions") == []


async def test_a_different_attached_sae_is_refused_before_any_trial() -> None:
    async with Session(Steering(attached_sae="evalfx-sae-other")) as s:
        result = await s.call("miassist_steering_serve", {"cluster": await saved(s), "prompt": "x"})
    assert result.is_error and result.content[0].text.startswith("sae_mismatch:")
    assert s.log("miserver", "POST", "/v1/chat/completions") == []


async def test_an_active_cluster_reads_active_from_health_and_status() -> None:
    st_ = Steering()
    async with Session(st_) as s:
        profile = await saved(s)
        first = data(await s.call("miassist_steering_serve", {"cluster": profile}))
        assert first["state"] != "active"
        st_.active = "sunny"  # the operator activated it in miServer
        got = data(await s.call("miassist_steering_serve", {"cluster": "sunny"}))
        status = await s.call("miassist_status", {"playbook": "steering", "subject": "sunny"})
    assert got["state"] == "active" and got["active"] is True
    assert status.structured_content["data"]["playbook"]["done"][-1] == "serve"


async def test_a_repeat_serve_adopts_the_imported_cluster_by_name() -> None:
    """OR1-pb-9: miServer's conflict is 422 "already exists", not 409; the repeat adopts it."""
    async with Session() as s:
        profile = await saved(s)
        first = data(await s.call("miassist_steering_serve", {"cluster": profile}))
        again = await s.call("miassist_steering_serve", {"cluster": profile})
    assert not again.is_error, again.content
    assert data(again)["miserver_cluster_id"] == first["miserver_cluster_id"]
    assert len(s.log("miserver", "POST", "/api/clusters/import")) == 2


# -- OR1-pb-5: the trial sends the cluster's features ------------------------------------------


async def test_the_trial_steers_with_the_clusters_triples() -> None:
    async with Session() as s:
        await s.call("miassist_steering_serve", {"cluster": await saved(s), "prompt": "Hi"})
    chat = s.log("miserver", "POST", "/v1/chat/completions")
    assert len(chat) == 1
    assert chat[0].body["steering"] == {
        "features": [{"index": 42, "strength": 1.0}],
        "sae_id": "evalfx-sae-1",
    }


async def test_a_cluster_with_no_member_is_never_tried_unsteered() -> None:
    st_ = Steering()
    st_.clusters.append(
        st_.cluster(
            {
                "name": "empty",
                "model": {"hf_id": "evalfx-org/evalfx-model"},
                "sae": {"mistudio_sae_id": "evalfx-sae-1"},
                "members": [],
            }
        )
    )
    async with Session(st_, installed=("miserver",)) as s:
        result = await s.call("miassist_steering_serve", {"cluster": "empty", "prompt": "Hi"})
    assert result.is_error and result.content[0].text.startswith("trial_no_features:")
    assert s.log("miserver", "POST", "/v1/chat/completions") == []


@pytest.mark.parametrize("status", ["blocked", "error"])
async def test_an_import_miserver_refused_is_said_not_served(status: str) -> None:
    async with Session(Steering(import_status=status)) as s:
        result = await s.call("miassist_steering_serve", {"cluster": await saved(s), "prompt": "x"})
    assert result.is_error and result.content[0].text.startswith("import_refused:")
    assert "SAE unbound" in result.content[0].text
    assert s.log("miserver", "POST", "/v1/chat/completions") == []


async def test_every_fake_answer_is_checked_against_the_apps_shapes() -> None:
    """The wiring of the shape check (control G15), not its existence."""
    async with Session() as s:
        await s.call("miassist_steering_serve", {"cluster": await saved(s), "prompt": "Hi"})
    for fake in (s.wb, s.sv):
        assert isinstance(fake, shapes.ShapedFakeApp)
        assert fake.checked >= 4 and fake.violations == []
