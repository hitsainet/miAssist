"""The steering playbook (005 FTASKS 0.2, 0.3, 1.1-1.7, 2.x-6.x, 7.1): pure modules, the live
registry and floor pins, and find / try / save / serve against fakes, on the request log."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest
from mcp import Client

from miassist.adapters import steering as st
from miassist.adapters.base import ANY, GateClass
from miassist.adapters.miworkbench import canonical_payload
from miassist.adapters.routes import ROUTES
from miassist.errors import MiAssistError
from miassist.guidance.loader import Guidance
from miassist.playbooks._shared import pending
from miassist.playbooks.registry import _validate
from miassist.playbooks.status import PROVIDERS
from miassist.playbooks.steering import fluency, strengths
from miassist.playbooks.steering.flow import STATES, Facts, derive
from tests.playbooks.steering.fake import COLLAPSED, FLUENT, Steering
from tests.playbooks.steering.support import Session, data
from tests.support.fake_apps import all_fakes
from tests.support.servers import make_server
from tests.support.vectors import VECTORS_FILE

ROOT = Path(__file__).resolve().parents[3]
WORDS = Guidance().playbooks["steering"].texts
SWEEP = "/api/v1/steering/async/sweep"
FILE = "/api/v1/mcp/approvals"

# -- pure (3.1, 3.2; FR-005.11, FR-005.13) ------------------------------------------------------


def test_default_strengths() -> None:
    assert strengths.default_strengths(10.0) == [0.5, 1.0, 1.5, 2.5, 4.0]
    assert strengths.default_strengths(10.0, "less") == [-0.5, -1.0, -1.5, -2.5, -4.0]
    assert strengths.default_strengths(2000.0)[-1] == 300.0
    for bad in (None, 0, -1.0, True):
        with pytest.raises(strengths.NoRealMaxActivation):
            strengths.default_strengths(bad)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "texts,usable,first",
    [
        ([FLUENT] * 3, 3.0, None),
        ([FLUENT, FLUENT, COLLAPSED], 2.0, 3.0),
        ([COLLAPSED] * 3, None, 1.0),
        ([FLUENT, "", FLUENT], 1.0, 2.0),
    ],
    ids=["no-collapse", "mid-collapse", "full-collapse", "empty-reply"],
)
def test_fluency_verdict(texts: list[str], usable: float | None, first: float | None) -> None:
    verdict = fluency.verdict(FLUENT, list(zip([1.0, 2.0, 3.0], texts, strict=True)))
    assert verdict.usable == usable and verdict.first_collapse == first
    assert [r["ttr"] for r in verdict.rows] == [fluency.ttr(t) for t in texts]


def test_ttr() -> None:
    assert (
        fluency.ttr("a b c d") == 1.0 and fluency.ttr(COLLAPSED) == 0.1 and fluency.ttr("") == 0.0
    )
    assert fluency.collapsed("one two three") and not fluency.collapsed(FLUENT)


TABLE = [
    (Facts(), "nothing_found"),
    (Facts(feature=True), "feature_chosen"),
    (Facts(feature=True, sweep_approval="pending"), "sweep_waiting"),
    (Facts(feature=True, sweep_approval="approved"), "sweep_approved"),
    (Facts(feature=True, sweep_task="started"), "sweeping"),
    (Facts(feature=True, sweep_task="success"), "swept"),
    (Facts(feature=True, combined_approval="pending"), "combined_waiting"),
    (Facts(feature=True, combined_task="progress"), "combining"),
    (Facts(profile=True), "saved"),
    (Facts(profile=True, model_load="pending"), "model_load_waiting"),
    (Facts(hub_pending=True), "awaiting_hub_import"),
    (Facts(imported=True), "imported"),
    (Facts(imported=True, trial_done=True), "awaiting_activation"),
    (Facts(imported=True, active=True), "active"),
    (Facts(feature=True, sweep_approval="rejected"), "rejected"),
    (Facts(feature=True, sweep_approval="expired"), "expired"),
    (Facts(feature=True, sweep_task="failure"), "failed"),
]


@pytest.mark.parametrize("facts,state", TABLE, ids=[s for _, s in TABLE])
def test_state_table(facts: Facts, state: str) -> None:
    assert derive(facts) == state


def test_every_state_reachable_and_worded() -> None:
    assert {s for _, s in TABLE} == set(STATES)
    for state in STATES:
        assert f"state.{state}" in WORDS


OVERCLAIM = re.compile(
    r"\b(controls|causes|represents|causal|safe)\b|\bfeature is\b", re.IGNORECASE
)


def test_no_overstatement_in_the_words() -> None:
    """3.5, FR-005.14: no verdict says a feature controls, causes, represents or is a concept;
    no causal claim (circuits get their rung's own words); no safe strength."""
    explain = Guidance().explain
    texts = list(WORDS.values())
    for tool in ("find", "try", "save", "serve"):
        for outcome in explain[f"miassist_steering_{tool}"].outcomes.values():
            texts += list(outcome.model_dump().values())
    for text in texts:
        assert not OVERCLAIM.search(text), text


def test_glossary_covers_the_terms() -> None:
    glossary = Guidance().glossary
    for key in (
        "feature",
        "sae",
        "layer",
        "steering-strength",
        "max-activation",
        "sweep",
        "fluent",
        "type-token-ratio",
        "cluster",
        "dial",
        "circuit",
        "rung",
        "activate",
        "trial",
    ):
        assert key in glossary, key


# -- the definition and the live registry (1.1, 1.4, 1.6) ----------------------------------------


def test_definition() -> None:
    raw = json.loads((ROOT / "src/miassist/playbooks/definitions/steering.json").read_text())
    playbook = _validate(raw, "steering.json")
    assert [s.id for s in playbook.steps] == ["find", "try", "save", "serve"]
    assert [s.entry for s in playbook.steps] == [True, False, False, True]
    assert [(s.done_when.pointer, s.done_when.op) for s in playbook.steps] == [
        ("/candidates/0", "exists"),
        ("/swept", "truthy"),
        ("/profile_id", "exists"),
        ("/active", "truthy"),
    ]
    for field in ("title", "steps", "requires_apps"):
        broken = dict(raw)
        del broken[field]
        with pytest.raises(SystemExit, match=field):
            _validate(broken, "steering.json")


HINTS = {
    "miassist_steering_find": (True, {"concept", "model", "limit"}),
    "miassist_steering_try": (
        False,
        {"feature", "prompt", "direction", "strengths", "approval_id", "task_id", "ask_again"},
    ),
    "miassist_steering_save": (
        False,
        {"name", "features", "prompt", "narrative", "approval_id", "task_id", "ask_again"},
    ),
    "miassist_steering_serve": (False, {"cluster", "circuit", "hub_repo", "prompt", "ask_again"}),
}


async def test_live_registry() -> None:
    mcp, _ = make_server(("miworkbench", "miserver"), all_fakes())
    async with Client(mcp) as client:
        tools = {t.name: t for t in (await client.list_tools()).tools}
        prompts = [p.name for p in (await client.list_prompts()).prompts]
    for name, (read_only, args) in HINTS.items():
        assert tools[name].annotations.read_only_hint is read_only, name
        assert tools[name].annotations.destructive_hint is False, name
        assert set(tools[name].input_schema["properties"]) == args, name
        schema = json.dumps(tools[name].input_schema)
        assert "activate" not in schema and "acknowledge" not in schema and "token" not in schema
    assert "steering" in prompts and PROVIDERS["steering"] is not None


@pytest.mark.parametrize(
    "installed,present",
    [
        (
            ("miworkbench",),
            {"miassist_steering_find", "miassist_steering_try", "miassist_steering_save"},
        ),
        (("miserver",), {"miassist_steering_serve"}),
        (("midataworks", "miforge"), set()),
    ],
)
async def test_tools_follow_the_apps(installed: tuple[str, ...], present: set[str]) -> None:
    mcp, _ = make_server(installed, all_fakes())
    async with Client(mcp) as client:
        names = {t.name for t in (await client.list_tools()).tools}
    assert {n for n in names if n.startswith("miassist_steering_")} == present


# -- routes and the floor (0.2, 0.3, 1.3, 1.7, 7.1) ---------------------------------------------

FLOOR = {
    "miworkbench.save_profile": (
        "POST",
        "/api/v1/cluster-profiles",
        "steering.save_profile",
        {},
        {},
    ),
    "miserver.import_cluster": (
        "POST",
        "/api/clusters/import",
        "steering.import_cluster",
        {"query.activate": ANY, "body.activate": ANY},
        {},
    ),
    "miserver.import_circuit": (
        "POST",
        "/api/circuits/import",
        "steering.import_circuit",
        {"query.activate": ANY, "body.activate": ANY},
        {},
    ),
    "miserver.test_chat": (
        "POST",
        "/v1/chat/completions",
        "steering.test_chat",
        {},
        {"X-miLLM-Load-Policy": "refuse"},
    ),
}


@pytest.mark.parametrize("route_id", sorted(FLOOR))
def test_floor_pin(route_id: str) -> None:
    method, path, entry, forbidden, headers = FLOOR[route_id]
    route = ROUTES.get(route_id)
    assert (route.method, route.path, route.gate, route.floor_entry) == (
        method,
        path,
        GateClass.UNGATED_WRITE,
        entry,
    )
    assert dict(route.forbidden) == forbidden and dict(route.headers) == headers


def test_the_chains_writes_are_the_table() -> None:
    writes = {r.id for r in st.STEERING_ROUTES if r.gate is GateClass.UNGATED_WRITE}
    assert writes == set(FLOOR)
    assert [r.id for r in st.STEERING_ROUTES if r.gate is GateClass.APP_GATED] == [
        "miserver.load_model"
    ]


NEVER = [
    ("POST", "/api/clusters/{cluster_id}/activate"),
    ("POST", "/api/clusters/{cluster_id}/deactivate"),
    ("PUT", "/api/clusters/active/intensity"),
    ("PUT", "/api/clusters/{cluster_id}/intensity"),
    ("POST", "/api/circuits/{circuit_id}/activate"),
    ("POST", "/api/circuits/{circuit_id}/deactivate"),
    ("PUT", "/api/circuits/active/intensity"),
    ("POST", "/api/clusters/hub/import"),
    ("POST", "/api/clusters/hub/search"),
    ("POST", "/api/v1/mcp/approvals/{request_id}/consume"),
]


@pytest.mark.parametrize("method,path", NEVER)
def test_never_registered(method: str, path: str) -> None:
    assert all((r.method, r.path) != (method, path) for r in ROUTES)


def test_no_a39_route_registered() -> None:
    """A39: none of miWorkbench's judge-run, spot-check, judge-prompt, enhanced-labelling or publish
    routes."""
    for route in ROUTES.for_app("miworkbench"):
        assert not re.search(r"judge|spot-check|enhanced-label|publish", route.path), route.id


def test_gpu_rows_literal_equals_the_vendored_vectors() -> None:
    """OVN-miassist-pb045-13: the steering GPU routes register only from 045's vendored rows; the
    literal must equal what the vendored file carries for steer_sweep and steer_combined."""
    vectors = json.loads(VECTORS_FILE.read_text())["vectors"]
    vendored = {
        (v["method"], v["route"], v["action"])
        for v in vectors
        if v["action"] in ("steer_sweep", "steer_combined")
    }
    assert {(v["method"], v["route"], v["action"]) for v in st.ENABLED_GPU_ROWS} == vendored
    registered = {
        r.id
        for r in ROUTES
        if r.file_first and r.approval_action in ("steer_sweep", "steer_combined")
    }
    assert registered == {r.id for r in st.gpu_routes(st.ENABLED_GPU_ROWS)}


def test_gpu_routes_register_from_rows() -> None:
    rows = [
        {"method": r.method, "route": r.path, "action": r.approval_action} for r in st.GPU_ROUTES
    ]
    assert st.gpu_routes(rows) == st.GPU_ROUTES and st.gpu_routes([]) == ()
    assert st.gpu_routes(rows[:1]) == st.GPU_ROUTES[:1]


@pytest.mark.parametrize(
    "kw",
    [
        {"params": {"activate": True}},
        {"params": {"activate": "1"}},
        {"json": {"name": "x", "activate": True}},
    ],
    ids=["query-true", "query-1", "body"],
)
async def test_import_never_carries_activate(kw: dict[str, Any]) -> None:
    """5.2, A20, R2M-11: refused forbidden_argument by Core; nothing sent."""
    async with Session() as s:
        client = s.deps.runtime.clients["miserver"]
        with pytest.raises(MiAssistError) as refused:
            await client.call(st.CLUSTERS_IMPORT, **kw)
        assert refused.value.code == "forbidden_argument" and s.sv.requests == []


# -- find (2.x) ---------------------------------------------------------------------------------


async def test_find_reads_only_and_hides_the_score() -> None:
    async with Session() as s:
        result = await s.call("miassist_steering_find", {"concept": "weather"})
    got = data(result)
    assert got["candidates"][0]["neuron_index"] == 42 and got["candidates"][0]["layer"] == 6
    assert got["candidates"][0]["label_source"] == "machine-written"
    assert "interpretability_score" not in json.dumps(result.structured_content)
    assert all(r.method == "GET" for r in s.wb.requests) and s.sv.requests == []


# -- try (3.3, 3.4) -----------------------------------------------------------------------------


async def try_(s: Session, **kw: Any) -> Any:
    return await s.call(
        "miassist_steering_try",
        {"feature": "evalfx-feat-1", "prompt": "Tell me about the day.", **kw},
    )


async def test_try_files_first_then_one_sweep_with_the_id() -> None:
    async with Session() as s:
        first = await try_(s)
        assert data(first)["state"] == "sweep_waiting"
        approval = first.structured_content["approval"]
        assert approval["decide_in"] == "miworkbench" and approval["then"] == "call_again_with"
        assert s.log("miworkbench", "POST", SWEEP) == []
        filed = s.log("miworkbench", "POST", FILE)
        assert len(filed) == 1 and filed[0].body["tool_name"] == "steer_sweep"
        payload = filed[0].body["payload"]
        assert payload["_method"] == "POST" and payload["_route"] == SWEEP
        assert (
            payload["strength_values"] == [0.5, 1.0, 1.5, 2.5, 4.0] and payload["feature_idx"] == 42
        )
        # a repeat while pending files nothing (digest of the whole filed payload, A43)
        again = await try_(s)
        assert (
            data(again)["state"] == "sweep_waiting" and len(s.log("miworkbench", "POST", FILE)) == 1
        )
        s.s.approve()
        result = await try_(s, approval_id=approval["id"])
    got = data(result)
    sweeps = s.log("miworkbench", "POST", SWEEP)
    assert len(sweeps) == 1 and sweeps[0].headers["x-mistudio-approval-request"] == approval["id"]
    assert (
        got["state"] == "swept" and got["usable_strength"] == 1.0 and got["first_collapse"] == 1.5
    )
    assert not [r for r in s.wb.requests if r.path.endswith("/consume")]
    # the literal agent header (the fake checks it against Core's own constant, so pin it here)
    assert {r.headers.get("x-mistudio-agent") for r in s.wb.requests} == {"miassist"}
    order = [
        (r.method, r.template)
        for r in s.wb.requests
        if r.template in (FILE, SWEEP, FILE + "/{request_id}")
    ]
    assert (
        order.index(("POST", FILE))
        < order.index(("GET", FILE + "/{request_id}"))
        < order.index(("POST", SWEEP))
    )
    assert "TTR below 0.4" in got["summary"]


async def test_digest_is_the_whole_filed_payload() -> None:
    async with Session() as s:
        await try_(s)
        filed = s.log("miworkbench", "POST", FILE)[0].body["payload"]
    body = {k: v for k, v in filed.items() if not k.startswith("_")}
    assert pending.digest(canonical_payload("POST", SWEEP, {}, {}, body)) == pending.digest(filed)
    assert pending.digest(body) != pending.digest(filed)


async def test_try_without_the_gpu_rows_is_a_calm_refusal() -> None:
    async with Session(gpu=False) as s:
        result = await try_(s)
    assert result.is_error and result.content[0].text.startswith("steering_gate_not_ready:")
    assert s.log("miworkbench", "POST", FILE) == [] and s.log("miworkbench", "POST", SWEEP) == []


@pytest.mark.parametrize("decision", ["denied", "expired"])
async def test_rejected_or_expired_sweep_is_not_refiled(decision: str) -> None:
    async with Session() as s:
        first = await try_(s)
        s.s.approve(decision)
        result = await try_(s, approval_id=first.structured_content["approval"]["id"])
        assert data(result)["state"] in ("rejected", "expired")
        assert result.structured_content["next_steps"][0]["args"]["ask_again"] is True
    assert (
        len(s.log("miworkbench", "POST", FILE)) == 1 and s.log("miworkbench", "POST", SWEEP) == []
    )


async def test_failed_task_is_a_step_failure() -> None:
    async with Session(Steering(task_states=["failure"])) as s:
        first = await try_(s)
        s.s.approve()
        result = await try_(s, approval_id=first.structured_content["approval"]["id"])
    assert result.is_error and result.content[0].text.startswith("sweep_failed:")


async def test_no_real_max_activation() -> None:
    async with Session(Steering(max_activation=0.0)) as s:
        result = await try_(s)
    assert result.is_error and result.content[0].text.startswith("no_real_max_activation:")
    assert s.log("miworkbench", "POST", FILE) == []


async def test_nothing_fluent_proposes_gentler_strengths() -> None:
    async with Session(Steering(sweep_texts=[COLLAPSED] * 5)) as s:
        first = await try_(s)
        s.s.approve()
        result = await try_(s, approval_id=first.structured_content["approval"]["id"])
    nxt = result.structured_content["next_steps"][0]
    assert nxt["tool"] == "miassist_steering_try" and nxt["args"]["strengths"] == [
        0.1,
        0.2,
        0.3,
        0.5,
    ]


# -- save (4.x) ---------------------------------------------------------------------------------


async def test_save_one_feature_with_a_dial_to_one() -> None:
    async with Session() as s:
        result = await s.call(
            "miassist_steering_save",
            {"name": "sunny", "features": [{"feature": "evalfx-feat-1", "strength": 1.0}]},
        )
        again = await s.call(
            "miassist_steering_save",
            {"name": "sunny", "features": [{"feature": "evalfx-feat-1", "strength": 1.0}]},
        )
    got = data(result)
    posts = s.log("miworkbench", "POST", "/api/v1/cluster-profiles")
    assert len(posts) == 1 and posts[0].body["budget"] == {
        "intensity": 1.0,
        "intensity_range": [0.0, 1.0],
    }
    assert posts[0].body["members"][0]["feature_idx"] == 42 and got["state"] == "saved"
    assert data(again)["profile_id"] == got["profile_id"]
    assert s.log("miworkbench", "POST", FILE) == []


async def test_save_two_features_checks_them_together_first() -> None:
    features = [
        {"feature": "evalfx-feat-1", "strength": 1.0},
        {"feature": "evalfx-feat-2", "strength": 0.5},
    ]
    async with Session() as s:
        first = await s.call(
            "miassist_steering_save", {"name": "pair", "features": features, "prompt": "Hi."}
        )
        assert data(first)["state"] == "combined_waiting"
        assert s.log("miworkbench", "POST", FILE)[0].body["tool_name"] == "steer_combined"
        assert s.log("miworkbench", "POST", "/api/v1/cluster-profiles") == []
        s.s.approve()
        done = await s.call(
            "miassist_steering_save",
            {
                "name": "pair",
                "features": features,
                "prompt": "Hi.",
                "approval_id": first.structured_content["approval"]["id"],
            },
        )
    assert data(done)["state"] == "saved" and data(done)["combined_check"]["fluent"] is True
    assert len(s.log("miworkbench", "POST", "/api/v1/steering/async/combined")) == 1


async def test_save_two_features_that_collapse_together_saves_nothing() -> None:
    features = [
        {"feature": "evalfx-feat-1", "strength": 1.0},
        {"feature": "evalfx-feat-2", "strength": 0.5},
    ]
    async with Session(Steering(combined_text=COLLAPSED)) as s:
        first = await s.call(
            "miassist_steering_save", {"name": "pair", "features": features, "prompt": "Hi."}
        )
        s.s.approve()
        done = await s.call(
            "miassist_steering_save",
            {
                "name": "pair",
                "features": features,
                "prompt": "Hi.",
                "approval_id": first.structured_content["approval"]["id"],
            },
        )
    assert done.is_error and done.content[0].text.startswith("combined_not_fluent:")
    assert s.log("miworkbench", "POST", "/api/v1/cluster-profiles") == []


async def test_without_miserver_the_save_ends_honestly() -> None:
    async with Session(installed=("miworkbench",)) as s:
        result = await s.call(
            "miassist_steering_save",
            {"name": "sunny", "features": [{"feature": "evalfx-feat-1", "strength": 1.0}]},
        )
    end = data(result)["honest_end"]
    assert (
        end
        == "Serving it needs miServer, which isn't part of this installation. The saved cluster is in miWorkbench."
    )


# -- serve (5.x) --------------------------------------------------------------------------------


async def saved(s: Session) -> str:
    result = await s.call(
        "miassist_steering_save",
        {"name": "sunny", "features": [{"feature": "evalfx-feat-1", "strength": 1.0}]},
    )
    return str(data(result)["profile_id"])


async def test_serve_imports_never_active_tries_once_and_hands_off() -> None:
    async with Session() as s:
        profile = await saved(s)
        result = await s.call("miassist_steering_serve", {"cluster": profile, "prompt": "Hello"})
        got = data(result)
        imports = s.log("miserver", "POST", "/api/clusters/import")
        assert len(imports) == 1 and imports[0].params == {"on_conflict": "fail"}
        assert "activate" not in json.dumps(imports[0].body)
        chats = s.log("miserver", "POST", "/v1/chat/completions")
        assert len(chats) == 1 and chats[0].headers["x-millm-load-policy"] == "refuse"
        assert chats[0].body["steering"]["features"][0]["index"] == 42
        assert (
            got["state"] == "awaiting_activation" and got["waiting"][0]["kind"] == "operator_action"
        )
        assert "operator" in got["waiting"][0]["detail"] and got["trial"]["excerpt"]
        # a second trial on the same cluster inside the hour: Core's floor limit, no second chat
        again = await s.call(
            "miassist_steering_serve", {"cluster": profile, "prompt": "Hello again"}
        )
    assert again.is_error and again.content[0].text.startswith("floor_limit:")
    assert len(s.log("miserver", "POST", "/v1/chat/completions")) == 1
    for r in s.sv.requests:
        assert r.headers["x-millm-agent"] == "agent:miassist"
        assert not re.search(r"/(activate|deactivate|intensity)$|/hub/", r.path), r.path


async def test_serve_loads_the_model_through_the_operator() -> None:
    async with Session(Steering(model_status="ready")) as s:
        profile = await saved(s)
        result = await s.call("miassist_steering_serve", {"cluster": profile})
        assert data(result)["state"] == "model_load_waiting"
        approval = result.structured_content["approval"]
        assert approval["decide_in"] == "miserver" and approval["then"] == "server_runs"
        again = await s.call("miassist_steering_serve", {"cluster": profile})
    assert data(again)["state"] == "model_load_waiting"
    assert len(s.log("miserver", "POST", "/api/models/{model_id}/load")) == 1


async def test_hub_repo_is_the_operators_import() -> None:
    async with Session(installed=("miserver",)) as s:
        result = await s.call("miassist_steering_serve", {"hub_repo": "evalfx-org/cluster"})
    assert data(result)["state"] == "awaiting_hub_import"
    assert all(r.method == "GET" for r in s.sv.requests)


async def test_active_cluster_is_done() -> None:
    st_ = Steering(active="sunny")
    st_.clusters.append(
        st_.cluster(
            {
                "name": "sunny",
                "model": {"hf_id": "evalfx-org/evalfx-model"},
                "sae": {"mistudio_sae_id": "evalfx-sae-1"},
                "members": [{"feature_idx": 42, "strength": 1.0}],
            },
            id="evalfx-cl-9",
        )
    )
    async with Session(st_, installed=("miserver",)) as s:
        result = await s.call("miassist_steering_serve", {"cluster": "sunny"})
        status = await s.call("miassist_status", {"playbook": "steering", "subject": "sunny"})
    assert data(result)["state"] == "active" and data(result)["active"] is True
    assert status.structured_content["data"]["playbook"]["finished"] is True


@pytest.mark.parametrize(
    "tool,app,args",
    [
        ("miassist_steering_find", "miworkbench", {"concept": "x"}),
        ("miassist_steering_serve", "miserver", {"cluster": "x"}),
    ],
)
async def test_down_app_is_unavailable(tool: str, app: str, args: dict[str, Any]) -> None:
    async with Session() as s:
        s.deps.runtime.detector.mark_unreachable(app, "connection refused")
        result = await s.call(tool, args)
    assert result.structured_content["unavailable"] == app


async def test_status_counts_done_when_once_per_step(monkeypatch: pytest.MonkeyPatch) -> None:
    from miassist.playbooks import done_when
    from miassist.playbooks.steering import status as status_module

    calls: list[Any] = []

    def counted(p: Any, v: Any) -> bool:
        calls.append(p)
        return done_when.evaluate_done_when(p, v)

    monkeypatch.setattr(status_module, "evaluate_done_when", counted)
    async with Session() as s:
        await saved(s)
        status = await s.call("miassist_status", {"playbook": "steering", "subject": "sunny"})
    got = status.structured_content["data"]["playbook"]
    assert len(calls) == 4 and got["done"] == ["find", "try", "save"] and got["where"] == "serve"


async def test_failed_after_consume_is_failed_not_waiting() -> None:
    """A29: a route that refused after consuming leaves the approval failed; shown as failed with a
    next step, never as waiting (7.2's "map failed to pending" control)."""
    async with Session() as s:
        first = await try_(s)
        s.s.approve("failed")
        result = await try_(s, approval_id=first.structured_content["approval"]["id"])
    got = data(result)
    assert got["state"] == "failed" and got["waiting"] == []
    assert result.structured_content["next_steps"][0]["args"]["ask_again"] is True
    assert s.log("miworkbench", "POST", SWEEP) == []


def test_vendored_request_schemas_are_derived() -> None:
    """003's design (OVN-miassist-pb003-1): the production lookup file equals a fresh derivation
    from the committed snapshot; it lists exactly the steering routes the vendored rows enable
    (integration OVN-miassist-int-18: rows 31 and 32)."""
    from scripts import write_request_schemas

    path = ROOT / "src/miassist/vendored/miworkbench_request_schemas.json"
    assert path.read_text() == write_request_schemas.text()
    steering = {k for k in json.loads(path.read_text())["routes"] if "steering" in k}
    assert steering == {f"{r['method']} {r['route']}" for r in st.ENABLED_GPU_ROWS}
