"""The 15-combination harness (001 FR-22, AC-3.1, AC-3.4, AC-5.2, AC-10.1, AC-10.2, AC-22.1, AC-22.3;
FTASKS 12.1, 12.5, 12.8). THE ONE combinations file (12.3): playbook chains 003-005 add their rows
to ``tests/fixtures/combinations.py`` and their completion cases here.

For each of the 15 non-empty installed sets and the empty set, the real ASGI app is built over
fake apps and driven through its HTTP transport:
1. the registered tool names equal the literal table, and the ``app`` enums equal the installed set;
2. the offered playbooks (guide and ``prompts/list``) equal the literal table;
3. NO COMPLAINT ABOUT AN ABSENT APP: across every result of the journey, the instructions, every
   tool's title, description and schema, the prompts, ``/health`` and every log record at WARNING or
   above, no absent app's id or display name appears, and no result is an error or ``unavailable``.
   The one exemption is Core's honest-end form: exact renderings by ``honest_end()`` for absent
   apps are removed before the scan (AC-22.3);
4. each installed app's start-here playbook completes step by step through the transport, with
   ``evaluate_done_when`` holding for every step, and its status then reads finished;
5. the instructions' bounds (FR-10).
"""

from __future__ import annotations

import itertools
import json
import logging
import re
from typing import Any

import pytest

from miassist.contracts.playbook import Playbook
from miassist.guidance.loader import Guidance
from miassist.playbooks.done_when import evaluate_done_when
from miassist.results.honest_end import honest_end
from tests.fixtures.combinations import APPS, COMBINATIONS
from tests.support.app_factory import client
from tests.support.fake_apps import all_fakes
from tests.support.http_mcp import HEADERS, call_tool, rpc
from tests.support.playbook_copies import definition
from tests.support.scenarios import URLS, seed, wait_probed

KEY = "abcdefghijklmnopqrstuvwxyz"
WORDS = Guidance()
SANCTIONED_FORM = re.compile(r"(isn't|aren't) part of this installation", re.IGNORECASE)


def label(installed: tuple[str, ...]) -> str:
    return "+".join(installed) or "empty"


def sanctioned(installed: tuple[str, ...]) -> list[str]:
    """Every honest-end rendering for a subset of the absent apps, longest first."""
    absent = [a for a in APPS if a not in installed]
    out = [
        honest_end(list(subset), installed)
        for n in range(1, len(absent) + 1)
        for subset in itertools.combinations(absent, n)
    ]
    return sorted(out, key=len, reverse=True)


def absence_findings(text: str, installed: tuple[str, ...]) -> list[str]:
    """What in ``text`` mentions an absent app, after removing the sanctioned honest ends."""
    for sentence in sanctioned(installed):
        text = text.replace(sentence, "")
    found = []
    for app in APPS:
        if app in installed:
            continue
        for name in (app, WORDS.app_name(app)):
            if re.search(re.escape(name), text, re.IGNORECASE):
                found.append(name)
    if SANCTIONED_FORM.search(text):
        found.append("an honest-end sentence that honest_end() did not render for absent apps")
    return found


def dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


class Journey:
    """One installed set's walk through the real app, with every text it produced."""

    def __init__(self, installed: tuple[str, ...], caplog: pytest.LogCaptureFixture) -> None:
        self.installed = installed
        self.texts: list[tuple[str, str]] = []
        self.results: list[tuple[str, dict[str, Any]]] = []
        self.tools: list[dict[str, Any]] = []
        self.prompts: list[str] = []
        self.instructions = ""
        self.completed: dict[str, list[tuple[str, bool]]] = {}
        self.finished: dict[str, bool] = {}
        caplog.set_level(logging.DEBUG)
        fakes = seed(all_fakes())
        with client(
            transports={a: f.transport() for a, f in fakes.items()},
            apps=",".join(installed),
            **URLS,
        ) as test_client:
            wait_probed(test_client)
            self._walk(test_client)
        self.logs = [r for r in caplog.records if r.levelno >= logging.WARNING]
        for record in self.logs:
            self.texts.append((f"log:{record.name}", record.getMessage() + dumps(vars(record))))

    def _call(self, test_client: Any, name: str, args: dict[str, Any]) -> dict[str, Any]:
        result = call_tool(test_client, f"/p/{KEY}/mcp", name, args)
        self.results.append((f"{name}{dumps(args)}", result))
        self.texts.append((f"result:{name}{dumps(args)}", dumps(result)))
        return result

    def _walk(self, test_client: Any) -> None:
        init = rpc(
            test_client,
            "/mcp",
            "initialize",
            {
                "protocolVersion": "2025-11-25",
                "capabilities": {},
                "clientInfo": {"name": "harness", "version": "1"},
            },
        )
        self.instructions = init.get("instructions") or ""
        self.texts.append(("instructions", self.instructions))
        listed = rpc(test_client, "/mcp", "tools/list")
        self.tools = listed["tools"]
        # Each tool's outputSchema is the published contract's assist_result, the same in every
        # installation (test_output_schemas_are_the_contract); its app vocabulary is the
        # contract's, so it is compared, not scanned. Everything else in the list is scanned.
        self.output_schemas = {t["name"]: t.get("outputSchema") for t in self.tools}
        scanned = [{k: v for k, v in t.items() if k != "outputSchema"} for t in self.tools]
        self.texts.append(("tools/list", dumps(scanned)))
        prompts = rpc(test_client, "/mcp", "prompts/list")
        self.prompts = [p["name"] for p in prompts["prompts"]]
        self.texts.append(("prompts/list", dumps(prompts)))
        health = test_client.get("/health").json()
        self.texts.append(("/health", dumps(health)))
        for topic in ("start", "apps", "playbooks", "approvals", "results", "glossary", "connect"):
            self._call(test_client, "miassist_guide", {"topic": topic})
        self._call(test_client, "miassist_status", {})
        self._call(test_client, "miassist_glossary", {})
        for app in self.installed:
            playbook = Playbook.model_validate(definition(f"start-{app}"))
            steps = []
            for step in playbook.steps:
                result = self._call(test_client, step.tool.root, dict(step.args or {}))
                data = (result.get("structuredContent") or {}).get("data")
                steps.append((step.id, evaluate_done_when(step.done_when, data)))
            self.completed[app] = steps
            status = self._call(test_client, "miassist_status", {"playbook": f"start-{app}"})
            self.finished[app] = status["structuredContent"]["data"]["playbook"]["finished"]
            self._call(
                test_client,
                "miassist_approval_status",
                {"app": app, "approval_id": "fx-approval-1"},
            )
        for name in ("start-" + a for a in self.installed):
            got = rpc(test_client, "/mcp", "prompts/get", {"name": name, "arguments": {}})
            self.texts.append((f"prompt:{name}", dumps(got)))


@pytest.fixture(scope="module")
def journeys() -> dict[str, Journey]:
    return {}


def journey(
    installed: tuple[str, ...], journeys: dict[str, Journey], caplog: pytest.LogCaptureFixture
) -> Journey:
    if label(installed) not in journeys:
        journeys[label(installed)] = Journey(installed, caplog)
    return journeys[label(installed)]


ROWS = [pytest.param(row, id=label(row[0])) for row in COMBINATIONS]


def test_sixteen_configurations() -> None:
    assert len(COMBINATIONS) == 16
    assert {row[0] for row in COMBINATIONS} == {
        c for n in range(5) for c in itertools.combinations(APPS, n)
    }


@pytest.mark.parametrize("row", ROWS)
def test_tool_names_and_app_enums(
    row: Any, journeys: dict[str, Journey], caplog: pytest.LogCaptureFixture
) -> None:
    installed, expected_tools, _ = row
    walk = journey(installed, journeys, caplog)
    assert tuple(t["name"] for t in walk.tools) == expected_tools
    for tool in walk.tools:
        app = tool["inputSchema"].get("properties", {}).get("app")
        if app is not None:
            values = app["enum"] if "enum" in app else [app["const"]]
            assert set(values) == set(installed), tool["name"]


def test_output_schemas_are_the_contract(
    journeys: dict[str, Journey], caplog: pytest.LogCaptureFixture
) -> None:
    """A tool's outputSchema is the same in every installation that registers the tool."""
    seen: dict[str, str] = {}
    for installed, _, _ in COMBINATIONS:
        for name, schema in journey(installed, journeys, caplog).output_schemas.items():
            assert schema is not None, name
            assert seen.setdefault(name, dumps(schema)) == dumps(schema), (name, installed)
    assert (
        len(seen) == 7 + 5 + 4 + 4
    )  # Core's seven, 003's five, 004's four, 005's four steering tools


@pytest.mark.parametrize("row", ROWS)
def test_offered_playbooks(
    row: Any, journeys: dict[str, Journey], caplog: pytest.LogCaptureFixture
) -> None:
    installed, _, expected = row
    walk = journey(installed, journeys, caplog)
    guide = dict(walk.results)['miassist_guide{"topic": "playbooks"}']
    offered = tuple(p["id"] for p in guide["structuredContent"]["data"]["playbooks"])
    assert offered == expected
    assert tuple(sorted(walk.prompts)) == expected


@pytest.mark.parametrize("row", ROWS)
def test_absence_silence(
    row: Any, journeys: dict[str, Journey], caplog: pytest.LogCaptureFixture
) -> None:
    installed = row[0]
    walk = journey(installed, journeys, caplog)
    assert walk.results, "no journey ran"
    for where, result in walk.results:
        assert result["isError"] is False, (where, result["content"])
        assert "unavailable" not in (result.get("structuredContent") or {}), where
    for where, text in walk.texts:
        assert absence_findings(text, installed) == [], where


@pytest.mark.parametrize("row", ROWS)
def test_start_here_completes(
    row: Any, journeys: dict[str, Journey], caplog: pytest.LogCaptureFixture
) -> None:
    installed = row[0]
    walk = journey(installed, journeys, caplog)
    assert set(walk.completed) == set(installed)
    for app, steps in walk.completed.items():
        assert [s for s, _ in steps] == ["look-around", "learn-a-word", "what-next"], app
        assert all(done for _, done in steps), (app, steps)
        assert walk.finished[app] is True, app


@pytest.mark.parametrize("row", ROWS)
def test_instructions_bounds(
    row: Any, journeys: dict[str, Journey], caplog: pytest.LogCaptureFixture
) -> None:
    walk = journey(row[0], journeys, caplog)
    text = walk.instructions
    assert 0 < len(text) < 4096
    head = text[:512]
    for needle in ("miassist_guide", "approval", "unavailable", "cannot approve"):
        assert needle in head, needle
    for app in row[0]:
        assert WORDS.app_name(app) in text


# -- AC-22.3: the honest-end exemption (12.8) ---------------------------------------------------


def fixture_result(sentence: str) -> str:
    return dumps({"structuredContent": {"data": {"honest_end": sentence}, "next_steps": []}})


def test_honest_end_exemption() -> None:
    installed = ("midataworks",)
    sanctioned_text = fixture_result(honest_end(["miserver"], installed))
    assert absence_findings(sanctioned_text, installed) == []
    any_of = fixture_result(honest_end(["miserver", "miforge"], installed))
    assert absence_findings(any_of, installed) == []


@pytest.mark.parametrize(
    "sentence",
    [
        "miServer is not installed",
        "miServer isn't part of the plan",
        "needs miDataworks, which isn't part of this installation",
        "needs miserver, which isn't part of this installation",
        "That needs miServer, which isn't part of this installation; ask miServer later",
    ],
    ids=[
        "plain-mention",
        "widened-exemption",
        "installed-app",
        "spelled-differently",
        "second-mention",
    ],
)
def test_honest_end_exemption_is_exact(sentence: str) -> None:
    assert absence_findings(fixture_result(sentence), ("midataworks",)) != []


def test_scan_sees_plants() -> None:
    """The absence scan itself: a planted absent name in any text form is found."""
    installed = ("miforge",)
    for plant in ("miServer", "MISERVER", "midataworks", "miWorkbench"):
        assert absence_findings(f"x {plant} y", installed), plant
    assert absence_findings("miForge only", installed) == []


# -- 12.2: one list, whatever the path, key, token or app state (AC-3.2, AC-3.3, AC-21.x) ------

K2 = "zyxwvutsrqponmlkjihgfedcba"
LIST_BODY = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}


def raw_list(test_client: Any, path: str, headers: dict[str, str] | None = None) -> bytes:
    response = test_client.post(path, json=LIST_BODY, headers={**HEADERS, **(headers or {})})
    assert response.status_code == 200, response.text
    return bytes(response.content)


@pytest.mark.parametrize("installed", [("miforge",), ("miserver", "midataworks"), APPS])
def test_list_identical_across_paths_keys_tokens_and_flips(installed: tuple[str, ...]) -> None:
    fakes = seed(all_fakes())
    with (
        client(
            transports={a: f.transport() for a, f in fakes.items()},
            apps=",".join(installed),
            **URLS,
        ) as first,
        client(
            transports={a: f.transport() for a, f in fakes.items()},
            apps=",".join(installed),
            **URLS,
        ) as second,
    ):
        wait_probed(first)
        wait_probed(second)
        bearer = {"authorization": "Bearer garbage-test-only"}
        lists = [
            raw_list(first, "/mcp"),
            raw_list(second, "/mcp"),
            raw_list(first, f"/p/{KEY}/mcp"),
            raw_list(first, f"/p/{K2}/mcp"),
            raw_list(first, "/mcp", bearer),
            raw_list(first, f"/p/{KEY}/mcp", bearer),
        ]
        runtime = first.app
        while not hasattr(runtime, "state"):
            runtime = runtime.app
        runtime.state.runtime.detector.mark_unreachable(installed[0], "connection refused")
        lists.append(raw_list(first, "/mcp"))
        lists.append(raw_list(first, f"/p/{K2}/mcp", bearer))
    assert json.loads(lists[0])["result"]["tools"], "an empty list would compare vacuously"
    assert all(item == lists[0] for item in lists), [
        i for i, x in enumerate(lists) if x != lists[0]
    ]


def test_deterministic_order() -> None:
    """AC-3.3: two builds from the same settings list the same tools in the same order."""
    from mcp import Client

    from tests.support.servers import make_server

    async def names() -> list[str]:
        mcp, _ = make_server(APPS, all_fakes())
        async with Client(mcp) as session:
            return [t.name for t in (await session.list_tools()).tools]

    import asyncio

    first, second = asyncio.run(names()), asyncio.run(names())
    assert first == second == sorted(first)


@pytest.mark.parametrize("installed", [(), ("miforge",), APPS], ids=["empty", "miforge", "all"])
async def test_both_protocol_eras(installed: tuple[str, ...]) -> None:
    """Spike S-3: the handshake era (2025-11-25) and the modern one (2026-07-28) see the same
    tools; the instructions arrive by the handshake and by discover."""
    from mcp import Client

    from tests.support.servers import make_server

    mcp, _ = make_server(installed, all_fakes())
    seen = {}
    for mode in ("legacy", "auto", "2026-07-28"):
        async with Client(mcp, mode=mode) as session:
            seen[mode] = (
                session.protocol_version,
                [json.loads(t.model_dump_json()) for t in (await session.list_tools()).tools],
                session.instructions,
            )
    assert seen["legacy"][0] == "2025-11-25" and seen["auto"][0] == "2026-07-28"
    assert seen["legacy"][1] == seen["auto"][1] == seen["2026-07-28"][1]
    assert seen["legacy"][2] == seen["auto"][2] == mcp.instructions


# -- 003: the detector-probe playbook in every combination (003 FPRD FR-003.5, §5.3; FTASKS 7.5) --

DETECTOR_APPS = {"miworkbench", "miserver", "midataworks"}
#: FR-003.5's additions to Core's AC-5.3 words, scanned when the cause is an absent app.
ABSENT_WORDS = (
    "error",
    "warning",
    "fail",
    "refus",
    "cannot",
    "unable",
    "unavailable",
    "missing",
    "not configured",
)


def detector_skipped(installed: tuple[str, ...]) -> list[str]:
    have = set(installed)
    out = []
    for step, apps in (
        ("describe", {"miworkbench", "midataworks"}),
        ("data", {"miworkbench", "midataworks"}),
        ("train", {"miworkbench"}),
        ("verdict", {"miworkbench"}),
        ("deploy", {"miserver"}),
    ):
        if not apps & have:
            out.append(step)
    return out


def detector_journey(installed: tuple[str, ...]) -> list[tuple[str, dict[str, Any]]]:
    """Walk §5.3's row for ``installed`` to its honest end; every result is returned."""
    from tests.playbooks.detector_probe.fakes import KEY, World
    from tests.playbooks.detector_probe.journey import journey as detector
    from tests.playbooks.detector_probe.test_train_verdict import report, trained, world_with_views
    from tests.support import dw_journey

    world = trained(world_with_views()) if "miworkbench" in installed else World()
    world.reports["evalfx-probe-1"] = report(2)
    world.behaviours.setdefault(KEY, {"key": KEY})
    # every step done, by miDataworks' own rule (R3 review fix OR3-int-3)
    world.dw_status[KEY] = {"objects": {}, "counts": dw_journey.counts_before(None)}
    world.sv_probes["evalfx-svprobe-1"] = {"id": "evalfx-svprobe-1", "name": "p", "armed": True}
    out = []
    with detector(installed, world) as j:

        def call(tool: str, args: dict[str, Any]) -> None:
            out.append((f"{tool}{dumps(args)}", j.call(tool, args)))

        call("miassist_status", {"playbook": "detector-probe", "subject": KEY})
        if "miworkbench" in installed:
            call("miassist_detector_verdict", {"key": KEY})
        elif "midataworks" in installed:
            call("miassist_detector_data", {"key": KEY, "route": "build_with_midataworks"})
        if "miserver" in installed:
            call("miassist_detector_deploy", {"probe": "evalfx-svprobe-1", "key": KEY})
        call("miassist_status", {"playbook": "detector-probe", "subject": KEY})
    return out


DETECTOR_ROWS = [r for r in ROWS if DETECTOR_APPS & set(r.values[0][0])]


@pytest.mark.parametrize("row", DETECTOR_ROWS)
def test_detector_probe_in_every_combination(row: Any) -> None:
    installed = row[0]
    results = detector_journey(installed)
    status = results[0][1]["structuredContent"]["data"]["playbook"]
    assert status["not_in_this_installation"] == detector_skipped(installed)
    ends = []
    for where, result in results:
        assert result["isError"] is False, (where, result["content"])
        assert "unavailable" not in (result.get("structuredContent") or {}), where
        text = dumps(result)
        assert absence_findings(text, installed) == [], where
        data = (result.get("structuredContent") or {}).get("data") or {}
        if data.get("honest_end"):
            ends.append(data["honest_end"])
            calm = dumps(result.get("structuredContent"))
            for sentence in sanctioned(installed):
                calm = calm.replace(sentence, "")
            assert not [w for w in ABSENT_WORDS if w in calm.lower()], where
    have = set(installed)
    if "miworkbench" in have and "miserver" not in have:
        assert ends == [
            "Your detector is evaluated. Serving it " + honest_end(["miserver"], installed) + "."
        ]
    elif "midataworks" in have and "miworkbench" not in have:
        assert ends == [
            "Your detector's data is built and checked. Training it "
            + honest_end(["miworkbench"], installed)
            + "."
        ]
    else:
        assert ends == []
    if "miserver" in have:
        deploy = next(r for w, r in results if w.startswith("miassist_detector_deploy"))
        assert deploy["structuredContent"]["data"]["state"] == "watching"
    final = results[-1][1]["structuredContent"]["data"]["playbook"]
    assert final["finished"] is True


# -- 004: the dataset playbook in every combination (004 FTASKS 6.2; FPRD FR-004.4, §5.3) ---------


def dataset_journey(
    installed: tuple[str, ...],
) -> tuple[list[tuple[str, dict[str, Any]]], dict[str, Any], list[bool]]:
    """find, build, check (the operator's run), publish, the operator's decision, publish again."""
    from tests.playbooks.dataset.fake import Dataworks

    dw = Dataworks(
        publish_status="published",
        check_run={
            "id": "evalfx-run-1",
            "status": "completed",
            "results": [
                {
                    "check": "C-1",
                    "outcome": "green",
                    "reason": "ok",
                    "next_step": "",
                    "evidence": {},
                }
            ],
        },
    )
    fakes = seed(all_fakes())
    dw.install(fakes["midataworks"])  # after seed: the playbook's routes answer from the fake
    path = f"/p/{KEY}/mcp"
    results: list[tuple[str, dict[str, Any]]] = []
    playbook = Playbook.model_validate(definition("dataset"))
    pointers = {s.tool.root: s.done_when for s in playbook.steps}
    done: list[bool] = []
    with client(
        transports={a: f.transport() for a, f in fakes.items()}, apps=",".join(installed), **URLS
    ) as tc:
        wait_probed(tc)

        def call(name: str, args: dict[str, Any]) -> dict[str, Any]:
            result = call_tool(tc, path, name, args)
            results.append((f"{name}{dumps(args)}", result))
            return result

        found = call("miassist_dataset_find", {"query": "support chats"})
        done.append(
            evaluate_done_when(
                pointers["miassist_dataset_find"], found["structuredContent"]["data"]
            )
        )
        built = call("miassist_dataset_build", found["structuredContent"]["next_steps"][0]["args"])
        done.append(
            evaluate_done_when(
                pointers["miassist_dataset_build"], built["structuredContent"]["data"]
            )
        )
        name = built["structuredContent"]["data"]["dataset_name"]
        checked = call("miassist_dataset_check", {"dataset": name, "check_run_id": "evalfx-run-1"})
        done.append(
            evaluate_done_when(
                pointers["miassist_dataset_check"], checked["structuredContent"]["data"]
            )
        )
        args = {"dataset": name, "repo_id": "evalfx-org/published", "confirm": True}
        call("miassist_dataset_publish", args)
        dw.decide("executed")  # the operator's decision, in miDataworks (never miAssist's)
        published = call("miassist_dataset_publish", args)
        done.append(
            evaluate_done_when(
                pointers["miassist_dataset_publish"], published["structuredContent"]["data"]
            )
        )
        status = call("miassist_status", {"playbook": "dataset", "subject": name})
    return results, status, done


DATASET_ROWS = [
    pytest.param(row, id=label(row[0])) for row in COMBINATIONS if "midataworks" in row[0]
]


@pytest.mark.parametrize("row", DATASET_ROWS)
def test_dataset_playbook_completes(row: Any) -> None:
    installed = row[0]
    assert "dataset" in row[2] and "miassist_dataset_find" in row[1]
    results, status, done = dataset_journey(installed)
    assert done == [True, True, True, True], done
    assert status["structuredContent"]["data"]["playbook"]["finished"] is True
    final = results[-2][1]["structuredContent"]
    assert final["data"]["state"] == "published" and final["data"]["honest_end"]
    if "miworkbench" in installed:
        assert final["next_steps"] and final["next_steps"][0]["tool"] == "miassist_guide"
    else:
        assert final["next_steps"] == []
    for where, result in results:
        assert result["isError"] is False, (where, result["content"])
        assert "unavailable" not in result["structuredContent"], where
        assert absence_findings(dumps(result), installed) == [], where


def test_dataset_rows_are_the_eight_with_midataworks() -> None:
    assert len(DATASET_ROWS) == 8
    for installed, tools, playbooks in COMBINATIONS:
        offered = "midataworks" in installed
        assert ("dataset" in playbooks) is offered
        assert ("miassist_dataset_find" in tools) is offered


# -- 005: the steering playbook in every combination (005 FTASKS 6.2; FPRD FR-005.4, §5.3) --------
# The try and the combined check need 045's steering GPU rows (OVN-miassist-pb045-13): until they
# are vendored, the walk covers find and save (miWorkbench) and serve (miServer); the full journey
# with the GPU gate runs on a test registry in tests/playbooks/steering/.


def steering_journey(installed: tuple[str, ...]) -> list[tuple[str, dict[str, Any]]]:
    from tests.playbooks.steering.fake import Steering

    s = Steering(active="sunny")
    if "miworkbench" not in installed:
        s.clusters.append(  # miServer's ClusterSummary shape (R1 review fix OR1-pb-4/-5)
            s.cluster(
                {
                    "name": "sunny",
                    "model": {"hf_id": "evalfx-org/evalfx-model"},
                    "sae": {"mistudio_sae_id": "evalfx-sae-1"},
                    "members": [{"feature_idx": 42, "strength": 1.0}],
                },
                id="evalfx-cl-1",
            )
        )
    fakes = seed(all_fakes())
    s.install(fakes["miworkbench"], fakes["miserver"])
    path = f"/p/{KEY}/mcp"
    results: list[tuple[str, dict[str, Any]]] = []
    with client(
        transports={a: f.transport() for a, f in fakes.items()}, apps=",".join(installed), **URLS
    ) as tc:
        wait_probed(tc)

        def call(name: str, args: dict[str, Any]) -> dict[str, Any]:
            result = call_tool(tc, path, name, args)
            results.append((f"{name}{dumps(args)}", result))
            return result

        target = "sunny"
        if "miworkbench" in installed:
            call("miassist_steering_find", {"concept": "weather"})
            saved = call(
                "miassist_steering_save",
                {"name": "sunny", "features": [{"feature": "evalfx-feat-1", "strength": 1.0}]},
            )
            target = saved["structuredContent"]["data"]["profile_id"]
        if "miserver" in installed:
            call("miassist_steering_serve", {"cluster": target})
        call("miassist_status", {"playbook": "steering", "subject": "sunny"})
    return results


STEERING_ROWS = [
    pytest.param(row, id=label(row[0]))
    for row in COMBINATIONS
    if {"miworkbench", "miserver"} & set(row[0])
]


@pytest.mark.parametrize("row", STEERING_ROWS)
def test_steering_playbook_walks(row: Any) -> None:
    installed = row[0]
    assert "steering" in row[2]
    results = steering_journey(installed)
    for where, result in results:
        assert result["isError"] is False, (where, result["content"])
        assert absence_findings(dumps(result), installed) == [], where
    status = results[-1][1]["structuredContent"]["data"]["playbook"]
    if "miserver" in installed:
        serve = results[-2][1]["structuredContent"]["data"]
        assert serve["state"] in ("active", "awaiting_activation"), serve["state"]
    if "miserver" not in installed:
        saved = next(r for w, r in results if w.startswith("miassist_steering_save"))
        assert saved["structuredContent"]["data"]["honest_end"].startswith(
            "Serving it needs miServer"
        )
    assert status["playbook_id"] == "steering"


def test_steering_rows_are_the_twelve_with_either_app() -> None:
    assert len(STEERING_ROWS) == 12
