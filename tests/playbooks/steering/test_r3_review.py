"""005 after review round 3 (review-int-r3, 2026-11-16): the walk texts (OR3-int-7) and the served
model matched by exact name (OR3-int-5, SW09)."""

from __future__ import annotations

from tests.playbooks.steering.fake import Steering
from tests.playbooks.steering.support import Session, data
from tests.playbooks.steering.test_real_shapes import approved_try, saved

LOAD = "/api/models/{model_id}/load"


async def test_after_the_sweep_the_offered_save_runs_as_given() -> None:
    async with Session(Steering(task_states=["success"])) as s:
        swept = await approved_try(s)
        offered = [x for x in swept.structured_content["next_steps"] if "save" in x["tool"]]
        assert offered and offered[0]["args"]["name"], offered
        saved_ = await s.call(offered[0]["tool"], offered[0]["args"])
    assert not saved_.is_error, saved_.content
    assert data(saved_)["state"] in ("saved", "combined_waiting")


async def test_the_save_summary_names_the_cluster() -> None:
    async with Session(Steering()) as s:
        result = await s.call(
            "miassist_steering_save",
            {"name": "sunny", "features": [{"feature": "evalfx-feat-1", "strength": 1.0}]},
        )
    assert data(result)["summary"].startswith("The cluster sunny is saved.")


async def test_an_approved_load_that_runs_says_it_is_loading_not_decide() -> None:
    st_ = Steering(model_status="ready")
    async with Session(st_) as s:
        cluster = await saved(s)
        await s.call("miassist_steering_serve", {"cluster": cluster})
        st_.sv_approvals[0]["status"] = "executing"
        got = data(await s.call("miassist_steering_serve", {"cluster": cluster}))
    assert got["state"] == "model_load_waiting"
    assert got["waiting"][0]["kind"] == "job" and "loading model" in got["waiting"][0]["detail"]
    assert "Decide in miServer" not in str(got), got
    assert len(s.log("miserver", "POST", LOAD)) == 1


async def test_the_served_model_is_matched_by_its_exact_name_not_a_decoy() -> None:
    decoy = {
        "id": 9,
        "name": "evalfx-model-large",
        "repo_id": "evalfx-org/evalfx-model-large",
        "status": "ready",
    }
    async with Session(Steering(model_status="loaded", other_models=[decoy])) as s:
        got = data(await s.call("miassist_steering_serve", {"cluster": await saved(s)}))
    assert got["state"] != "model_load_waiting", got
    assert s.log("miserver", "POST", LOAD) == []
