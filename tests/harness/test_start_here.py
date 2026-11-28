"""Start-here playbooks are stateless (001 FR-23, AC-23.5, AC-23.6; FTASKS 11.2, 11.5; A25).

In each one-app installation, with a fresh key and an empty store, ``miassist_status(playbook=
"start-<app>")`` already reports ``look-around`` done, makes exactly FR-24's overview reads for that
app once each, and writes no row. Each start-here step's tool, run through the client with the
step's ``args``, satisfies its ``done_when``.
"""

from __future__ import annotations

import pytest

from miassist.contracts.playbook import Playbook
from miassist.playbooks.done_when import evaluate_done_when
from tests.support.app_factory import client
from tests.support.fake_apps import all_fakes
from tests.support.http_mcp import call_tool
from tests.support.memory_store import MemoryStore
from tests.support.playbook_copies import definition
from tests.support.scenarios import URLS, Scenario, run, seed, wait_probed

KEY = "abcdefghijklmnopqrstuvwxyz"
APPS = ("miworkbench", "miserver", "midataworks", "miforge")
#: FR-24's reads, literally (not derived from the code under test).
OVERVIEW = {
    "miworkbench": [
        "/api/v1/models",
        "/api/v1/saes",
        "/api/v1/datasets",
        "/api/v1/probe-monitors/probes",
    ],
    "miserver": ["/api/models", "/api/probes/status", "/api/clusters"],
    "midataworks": ["/api/v1/datasets", "/api/v1/versions"],
    "miforge": ["/api/v1/runs", "/api/v1/packs", "/api/v1/checkpoints"],
}


@pytest.mark.parametrize("app", APPS)
def test_stateless_progress(app: str) -> None:
    store = MemoryStore()
    scenario = Scenario(
        f"status-start-{app}", (app,), "miassist_status", {"playbook": f"start-{app}"}
    )
    done = run(scenario, key=KEY, store=store)
    assert done.result["isError"] is False, done.result["content"]
    status = done.result["structuredContent"]["data"]["playbook"]
    assert status["playbook_id"] == f"start-{app}" and status["playbook_version"] == 1
    assert "look-around" in status["done"]
    assert status["done"] == ["look-around", "learn-a-word", "what-next"]
    assert status["finished"] is True and status["where"] is None and status["next"] is None
    assert [(a, m, p) for a, m, p, _, _ in done.app_requests()] == [
        (app, "GET", path) for path in OVERVIEW[app]
    ]
    assert store.write_calls == 0 and store.levels == {} and store.progresses == {}


@pytest.mark.parametrize("app", APPS)
def test_progress_follows_the_live_read(app: str) -> None:
    """With the app down, ``look-around`` is not done: the provider reads live, not a record."""

    def down(_fakes: object, deps: object) -> None:
        deps.runtime.detector.mark_unreachable(app, "connection refused")  # type: ignore[attr-defined]

    scenario = Scenario(
        f"status-start-{app}-down",
        (app,),
        "miassist_status",
        {"playbook": f"start-{app}"},
        prepare=down,
    )
    status = run(scenario, key=KEY).result["structuredContent"]["data"]["playbook"]
    assert status["where"] == "look-around" and "look-around" not in status["done"]
    assert status["next"] == {
        "tool": "miassist_overview",
        "args": {"app": app},
        "why": status["next"]["why"],
    }
    assert status["finished"] is False


@pytest.mark.parametrize("app", APPS)
def test_args_satisfy_done_when(app: str) -> None:
    playbook = Playbook.model_validate(definition(f"start-{app}"))
    fakes = seed(all_fakes())
    with client(
        transports={a: f.transport() for a, f in fakes.items()}, apps=app, **URLS
    ) as test_client:
        wait_probed(test_client)
        for step in playbook.steps:
            assert step.args is not None, step.id
            result = call_tool(test_client, "/mcp", step.tool.root, step.args)
            assert result["isError"] is False, (step.id, result["content"])
            data = result["structuredContent"]["data"]
            assert evaluate_done_when(step.done_when, data), (app, step.id)
