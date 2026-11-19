"""005's round-2 review fixes (review-int-r2, 2026-11-16): the model load after approval, the one
bounded trial, and 003's request-schema check before filing.

The reviewer's probes (``probes/test_r2_probe_model_load_dup.py`` and ``test_r2_trial_bound.py``)
are adopted as the first and third tests.
"""

from __future__ import annotations

from typing import Any

import pytest

from miassist.vendored import requests as vendored
from tests.playbooks.steering.fake import Steering
from tests.playbooks.steering.support import Session, data
from tests.playbooks.steering.test_real_shapes import saved

LOAD = "/api/models/{model_id}/load"
FILE = "/api/v1/mcp/approvals"
TWO = [{"feature": "evalfx-feat-1", "strength": 1.0}, {"feature": "evalfx-feat-2", "strength": 0.5}]


# -- R2 review fix (OR2-int-1): a load the operator approved, running on miServer ---------------


@pytest.mark.parametrize("model_now", ["loading", "ready"])
async def test_a_repeat_serve_while_the_approved_load_runs_files_nothing_new(
    model_now: str,
) -> None:
    """``ready``: miServer runs the approved load (``executing``) before the model row says
    ``loading``; only the executing request then stops a second filing."""
    st_ = Steering(model_status="ready")
    async with Session(st_) as s:
        cluster = await saved(s)
        first = await s.call("miassist_steering_serve", {"cluster": cluster})
        assert data(first)["state"] == "model_load_waiting"
        # the operator approves: miServer runs it (executing) and the model is loading
        st_.sv_approvals[0]["status"] = "executing"
        st_.model_status = model_now
        again = await s.call("miassist_steering_serve", {"cluster": cluster})
    assert data(again)["state"] == "model_load_waiting"
    assert len(s.log("miserver", "POST", LOAD)) == 1, "a second model_load was filed"


@pytest.mark.parametrize("ask_again", [False, True])
async def test_a_loading_model_is_waited_on_never_loaded_again(ask_again: bool) -> None:
    """The model is ``loading`` and no request of miAssist's is listed (the operator started the
    load in miServer): serve waits on it and files nothing, even when asked again."""
    async with Session(Steering(model_status="loading")) as s:
        cluster = await saved(s)
        result = await s.call(
            "miassist_steering_serve", {"cluster": cluster, "ask_again": ask_again}
        )
    got = data(result)
    assert got["state"] == "model_load_waiting"
    assert got["waiting"][0]["kind"] == "job" and "loading model" in got["waiting"][0]["detail"]
    assert s.log("miserver", "POST", LOAD) == []


# -- R2 review fix (OR2-int-2): the one bounded trial (floor steering.test_chat) -----------------


async def test_the_trial_is_bounded_to_96_tokens_and_never_loads() -> None:
    async with Session(Steering(model_status="loaded")) as s:
        await s.call("miassist_steering_serve", {"cluster": await saved(s), "prompt": "Hi."})
    chats = s.log("miserver", "POST", "/v1/chat/completions")
    assert len(chats) == 1
    assert chats[0].body["max_tokens"] == 96
    assert chats[0].headers.get("x-millm-load-policy") == "refuse"
    assert s.log("miserver", "POST", LOAD) == []


# -- R2 review fix (OR2-int-7): 003's request-schema check before anything is filed -------------


async def _try(s: Session) -> Any:
    return await s.call("miassist_steering_try", {"feature": "evalfx-feat-1", "prompt": "Hi."})


async def _save(s: Session) -> Any:
    return await s.call(
        "miassist_steering_save", {"name": "pair", "features": TWO, "prompt": "Hi."}
    )


@pytest.mark.parametrize(
    "which,path",
    [("try", "/api/v1/steering/async/sweep"), ("save", "/api/v1/steering/async/combined")],
)
async def test_each_filed_request_is_checked_once_against_the_route_schema(
    which: str, path: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[tuple[str, Any, Any]] = []
    real = vendored.refusals

    def spy(route: Any, query: Any, body: Any) -> list[str]:
        seen.append((route.path, dict(query), body))
        return real(route, query, body)

    monkeypatch.setattr(vendored, "refusals", spy)
    async with Session() as s:
        await (_try(s) if which == "try" else _save(s))
    filed = s.log("miworkbench", "POST", FILE)
    assert len(filed) == 1 and len(seen) == 1, (filed, seen)
    route_path, query, body = seen[0]
    assert route_path == path and query == {}
    sent = {k: v for k, v in filed[0].body["payload"].items() if not k.startswith("_")}
    assert body == sent, "the checked payload is not the one filed"


@pytest.mark.parametrize("which", ["try", "save"])
async def test_a_request_the_route_schema_refuses_is_never_filed(
    which: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(vendored, "refusals", lambda *a: ["body.prompt: too long"])
    async with Session() as s:
        result = await (_try(s) if which == "try" else _save(s))
    assert result.is_error and "invalid_arguments" in str(result.content), result
    assert "body.prompt: too long" in str(result.content)
    assert s.log("miworkbench", "POST", FILE) == []
    assert s.log("miworkbench", "GET", FILE) == [], "the repeat lookup ran before the refusal"
