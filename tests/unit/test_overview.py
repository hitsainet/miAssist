"""``miassist_overview`` of an empty app (001 FR-24, AC-24.2; FTASKS 10.10; R1 review fix
OR1-001-5, 2026-11-16): counts of 0 and a ``next_steps`` entry that starts the matching playbook
when one is offered, else the app's start-here. The same at both levels (FR-7)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from mcp import Client

from miassist.guidance.loader import Guidance
from miassist.playbooks import status as status_module
from miassist.tools.core import OVERVIEW_READS, summarise
from tests.support.fake_apps import all_fakes
from tests.support.playbook_copies import (
    FIXTURE_WORDS,
    copy_definitions,
    copy_guidance,
    fixture_definition,
    write_definition,
    write_words,
)
from tests.support.scenarios import POPULATED, refuse_overview, seed, unreadable_overview
from tests.support.servers import make_server

APPS = ("miworkbench", "miserver", "midataworks", "miforge")


async def overview(app: str, *, empty: bool, **server: Any) -> Any:
    fakes = seed(all_fakes(), empty=empty)
    mcp, deps = make_server((app,), fakes, **server)
    await deps.runtime.detector.probe_all()
    async with Client(mcp) as client:
        return await client.call_tool("miassist_overview", {"app": app})


#: AC-24.2 with the shipped playbooks, written by hand (integration OVN-miassist-int-9, 2026-11-16):
#: an empty app's overview starts the first offered playbook that lists the app, else its
#: start-here. Each chain that ships a playbook edits this table.
EMPTY_APP_NEXT = {
    "miworkbench": "detector-probe",  # 003
    "miserver": "detector-probe",  # 003
    "midataworks": "dataset",  # 004 (offered before 003's detector-probe)
    "miforge": "start-miforge",
}


@pytest.mark.parametrize("app", APPS)
async def test_empty_app(app: str) -> None:
    result = await overview(app, empty=True)
    assert not result.is_error, result.content
    data = result.structured_content["data"]
    counts = [v["count"] for v in data["lists"].values() if "count" in v]
    assert counts and all(c == 0 for c in counts)
    (next_step,) = result.structured_content["next_steps"]
    assert (next_step["tool"], next_step["args"]) == (
        "miassist_guide",
        {"playbook": EMPTY_APP_NEXT[app]},
    )


@pytest.mark.parametrize("app", APPS)
async def test_populated_app_points_at_the_playbooks(app: str) -> None:
    result = await overview(app, empty=False)
    (next_step,) = result.structured_content["next_steps"]
    assert (next_step["tool"], next_step["args"]) == ("miassist_guide", {"topic": "playbooks"})


async def test_matching_playbook_wins(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = copy_guidance(tmp_path)
    write_words(root, "fixture-pb", FIXTURE_WORDS)
    folder = copy_definitions(tmp_path)
    write_definition(folder, fixture_definition())
    monkeypatch.setitem(status_module.PROVIDERS, "fixture-pb", status_module.GENERIC)
    result = await overview("miforge", empty=True, words=Guidance(root), definitions=folder)
    (next_step,) = result.structured_content["next_steps"]
    assert next_step["args"] == {"playbook": "fixture-pb"}


# -- R2 review fix (OR2-001-4), 2026-11-16: refused reads are not an empty app -----------------


async def overview_over(app: str, fakes: Any, **server: Any) -> Any:
    mcp, deps = make_server((app,), fakes, **server)
    await deps.runtime.detector.probe_all()
    async with Client(mcp) as client:
        return await client.call_tool("miassist_overview", {"app": app})


def texts(result: Any) -> str:
    return " ".join(str(v) for v in result.structured_content.get("explain", {}).values())


@pytest.mark.parametrize("app", APPS)
async def test_every_read_refused_is_said_plainly(app: str) -> None:
    """Unseeded fakes answer each overview read with the app's own 404 envelope."""
    result = await overview_over(app, all_fakes())
    assert not result.is_error, result.content
    content = result.structured_content
    lists = content["data"]["lists"]
    assert lists and all("error" in v for v in lists.values()), lists
    words = texts(result)
    assert "refused every list" in words
    assert "nothing is wrong" not in words and "found nothing" not in words
    (next_step,) = content["next_steps"]
    assert next_step["tool"] == "miassist_status"
    playbooks = [s.get("args", {}).get("playbook") for s in content["next_steps"]]
    assert playbooks == [None], playbooks


@pytest.mark.parametrize("app", APPS)
async def test_some_reads_refused_is_partial(app: str) -> None:
    """The first read answers an empty list, the others are refused: partial, never empty, and
    no start-here (the same at expert: scenario ``overview-<app>-refused`` in the level harness)."""
    fakes = seed(all_fakes(), empty=True)
    refuse_overview(app, keep=1)(fakes, None)
    result = await overview_over(app, fakes)
    content = result.structured_content
    lists = content["data"]["lists"]
    assert any("error" in v for v in lists.values()) and any("count" in v for v in lists.values())
    words = texts(result)
    assert "refused the others" in words
    assert "nothing is wrong" not in words
    (next_step,) = content["next_steps"]
    assert next_step["args"] == {"topic": "playbooks"}


async def test_another_apps_start_here_is_never_this_apps_match(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R2 review fix (OR2-001-8): a start-here playbook that lists this app (another app's
    start-here, say) is not "the matching playbook"; an empty app still gets its own start-here."""
    root = copy_guidance(tmp_path)
    write_words(root, "start-aaa", FIXTURE_WORDS)
    folder = copy_definitions(tmp_path)
    write_definition(folder, fixture_definition("start-aaa", requires=["miforge"]))
    monkeypatch.setitem(status_module.PROVIDERS, "start-aaa", status_module.GENERIC)
    result = await overview("miforge", empty=True, words=Guidance(root), definitions=folder)
    offered = {s["args"].get("playbook") for s in result.structured_content["next_steps"]}
    assert offered == {"start-miforge"}


# -- R3 review fix (OR3-001-2), 2026-11-16: an unreadable answer is not an empty app ----------


@pytest.mark.parametrize("app", APPS)
@pytest.mark.parametrize("empty", [False, True], ids=["populated", "empty-seed"])
async def test_unknown_shape_is_not_an_empty_app(app: str, empty: bool) -> None:
    """The reviewer's proposed test: overview reads answering 200 in an unknown envelope."""
    fakes = seed(all_fakes(), empty=empty)
    unreadable_overview(app)(fakes, None)
    result = await overview_over(app, fakes)
    assert not result.is_error, result.content
    content = result.structured_content
    assert "answered every list miAssist asked for, but in a shape" in texts(result)
    lists = content["data"]["lists"]
    assert set(lists) == {name for name, _, _ in OVERVIEW_READS[app]}
    assert all(v == {"error": "overview_unreadable"} for v in lists.values()), lists
    words = texts(result)
    assert "found nothing" not in words and "nothing is wrong" not in words, words
    assert "could not read" in words and "not an empty app" in words, words
    (next_step,) = content["next_steps"]
    assert next_step["tool"] == "miassist_status"
    playbooks = [s.get("args", {}).get("playbook") for s in content["next_steps"]]
    assert f"start-{app}" not in playbooks, playbooks


@pytest.mark.parametrize("app", APPS)
async def test_some_reads_unreadable_is_partial(app: str) -> None:
    fakes = seed(all_fakes(), empty=True)
    unreadable_overview(app, keep=1)(fakes, None)
    result = await overview_over(app, fakes)
    content = result.structured_content
    assert "or answered them in a shape miAssist could not read" in texts(result)
    lists = content["data"]["lists"]
    assert [v.get("error") for v in lists.values()][1:] == ["overview_unreadable"] * (
        len(lists) - 1
    )
    assert "nothing is wrong" not in texts(result)
    (next_step,) = content["next_steps"]
    assert next_step["args"] == {"topic": "playbooks"}


async def test_refused_and_unreadable_together_is_refused() -> None:
    fakes = seed(all_fakes(), empty=True)
    refuse_overview("midataworks", keep=1)(fakes, None)
    fakes["midataworks"].on("GET", POPULATED["midataworks"][0][0], "a string, not a list")
    result = await overview_over("midataworks", fakes)
    assert "refused every list" in texts(result)


@pytest.mark.parametrize(
    "body",
    [
        {"results_v2": {"rows": "moved"}, "ok": True},
        {"items": "not a list"},
        {"total": True},
        "a string",
        None,
        7,
    ],
)
def test_summarise_marks_an_unknown_shape_unreadable(body: Any) -> None:
    assert summarise("datasets", body) == {"error": "overview_unreadable"}


@pytest.mark.parametrize(
    ("name", "body", "expected"),
    [
        ("datasets", [], {"count": 0, "at_least": False, "newest": []}),
        ("datasets", {"items": []}, {"count": 0, "at_least": False, "newest": []}),
        ("datasets", {"total": 0}, {"count": 0, "at_least": False, "newest": []}),
        ("probes", {"data": {"armed": 0}}, {"counts": {"armed": 0}}),
        ("probes", {"data": {"armed": True}}, {"error": "overview_unreadable"}),
        ("probes", {"results_v2": {}}, {"error": "overview_unreadable"}),
    ],
)
def test_summarise_known_shapes(name: str, body: Any, expected: dict[str, Any]) -> None:
    assert summarise(name, body) == expected


#: miForge's ``GET /api/v1/runs`` answer as ``runs_index.list_runs`` builds it (miForge ``c8230db``,
#: ``backend/src/api/v1/endpoints/runs_index.py:56-72`` and ``:150-159``): each row names its run
#: ``run_id`` and carries no ``name`` or ``id``.
MIFORGE_RUNS = {
    "runs": [
        {
            "run_id": f"run_fx{i}",
            "status": "succeeded",
            "run_type": "sft",
            "created_at": "2026-11-26T00:00:00Z",
            "finished_at": None,
            "last_step": None,
            "stop_reason": None,
            "failure_code": None,
            "archived_at": None,
        }
        for i in (3, 2, 1)
    ],
    "total": 9,
    "limit": 3,
    "offset": 0,
    "include_archived": False,
    "statuses": ["pending", "running", "succeeded"],
    "run_types": ["sft"],
}


def test_summarise_names_miforge_runs_by_their_run_id() -> None:
    """ENH-012 acceptance (review/enh012-acceptance, 2026-11-26): the live overview answered
    miForge ``runs: {count: 9, newest: []}``, because the label read only ``name``,
    ``display_name`` and ``id``, and the scenario's run row had a ``name`` miForge never sends.
    AC-24.1 promises up to three of the newest names."""
    assert summarise("runs", MIFORGE_RUNS) == {
        "count": 9,
        "at_least": False,
        "newest": ["run_fx3", "run_fx2", "run_fx1"],
    }


async def test_the_miforge_overview_names_its_runs() -> None:
    """The same through the tool, over the scenario's miForge (which now answers the real row)."""
    result = await overview("miforge", empty=False)
    assert result.structured_content["data"]["lists"]["runs"]["newest"] == ["fx-run"]


# -- Overview fix (2026-11-27): names stay distinguishable, counts are the list's total, newest
# -- means newest. Found live after the acceptance push (059b613): ``miassist_overview("miforge")``
# -- named two checkpoints ``hf:LiquidAI/LFM2.5-1.2B-Instruct@0f60...431b:f11w6-`` (cut at 80
# -- characters) and counted ``3`` while miForge held 4. Every answer below is built from the
# -- app's vendored response shape and checked against it (``ShapedFakeApp``).

#: The live checkpoint names of 2026-11-26 (``forge_list_all_checkpoints``), and their times.
BASE = "hf:LiquidAI/LFM2.5-1.2B-Instruct@0f604ada3f766f9f257460c4c9f0b5d6f69d431b"
LIVE_CHECKPOINTS = [  # miForge's order: by name (``reindex.list_checkpoints``)
    (f"{BASE}:deps-smoke-20261022-0357:step-20", "2026-10-22T09:44:45+00:00"),
    (f"{BASE}:f11w6-l1:step-100", "2026-10-20T13:12:16+00:00"),
    (f"{BASE}:f11w6-l1:step-50", "2026-10-20T13:12:02+00:00"),
    (f"{BASE}:py313-smoke-20261021-1653:step-20", "2026-10-21T16:53:00+00:00"),
]


def checkpoints_answer(rows: list[tuple[str, str]], *, total: int | None = None) -> Any:
    from tests.support.scenarios import answer

    return answer(
        "miforge",
        "/api/v1/checkpoints",
        checkpoints=[{"name": n, "created_at": t} for n, t in rows],
        count=len(rows),
        total=len(rows) if total is None else total,
    )


async def shaped_overview(app: str, answers: dict[str, Any]) -> tuple[Any, Any]:
    """The overview of ``app`` over a shape-checked fake answering ``answers`` (path → body);
    every other overview read answers the seeded (also real-shaped) populated answer."""
    from tests.support.scenarios import POPULATED
    from tests.support.shapes import shaped_fakes

    fakes = shaped_fakes((app,))
    for path, body in POPULATED[app]:
        fakes[app].on("GET", path, answers.get(path, body))
    mcp, deps = make_server((app,), fakes)
    await deps.runtime.detector.probe_all()
    async with Client(mcp) as client:
        result = await client.call_tool("miassist_overview", {"app": app})
    fake = fakes[app]
    # miForge's health route has no vendored shape; the overview reads are what is checked here
    read = [f"{app} GET {path} " for path, _ in POPULATED[app]]
    found = [v for v in fake.violations if any(v.startswith(r) for r in read)]  # type: ignore[attr-defined]
    assert found == [], found
    assert sum(r.path in dict(POPULATED[app]) for r in fake.requests) == len(POPULATED[app])
    assert not result.is_error, result.content
    return result.structured_content["data"]["lists"], fake


async def test_checkpoints_sharing_a_long_prefix_keep_their_whole_names() -> None:
    lists, fake = await shaped_overview(
        "miforge", {"/api/v1/checkpoints": checkpoints_answer(LIVE_CHECKPOINTS)}
    )
    assert [r.params for r in fake.requests if r.path == "/api/v1/checkpoints"] == [
        {"limit": "1000"}
    ]
    checkpoints = lists["checkpoints"]
    # newest first by ``created_at``, not miForge's name order, and every name whole
    assert checkpoints == {
        "count": 4,
        "at_least": False,
        "newest": [
            f"{BASE}:deps-smoke-20261022-0357:step-20",
            f"{BASE}:py313-smoke-20261021-1653:step-20",
            f"{BASE}:f11w6-l1:step-100",
        ],
    }


async def test_a_checkpoint_count_is_the_total_not_the_page() -> None:
    """miForge sends ``count`` as the page's length beside ``total`` (``checkpoints.py``)."""
    lists, _ = await shaped_overview(
        "miforge", {"/api/v1/checkpoints": checkpoints_answer(LIVE_CHECKPOINTS[:3], total=4)}
    )
    assert lists["checkpoints"]["count"] == 4
    assert lists["checkpoints"]["at_least"] is False
    # the names are the newest of the page read, and say so
    assert lists["checkpoints"]["newest_of"] == 3


async def test_miworkbench_counts_come_from_its_pagination_total() -> None:
    from tests.support.scenarios import answer

    rows = [{"name": f"fx-model-{i}"} for i in (3, 2, 1)]
    page = {"page": 1, "limit": 3, "total": 7, "total_pages": 3, "has_next": True}
    lists, _ = await shaped_overview(
        "miworkbench",
        {"/api/v1/models": answer("miworkbench", "/api/v1/models", data=rows, pagination=page)},
    )
    assert lists["models"] == {
        "count": 7,
        "at_least": False,
        "newest": ["fx-model-3", "fx-model-2", "fx-model-1"],
    }


async def test_name_ordered_lists_are_put_newest_first() -> None:
    """miDataworks answers its datasets by name; the overview names the newest three."""
    from tests.support.scenarios import answer

    rows = [
        {"name": "a-oldest", "created_at": "2026-10-01T00:00:00Z"},
        {"name": "b-newest", "created_at": "2026-11-20T00:00:00Z"},
        {"name": "c-middle", "created_at": "2026-11-01T00:00:00Z"},
        {"name": "d-second", "created_at": "2026-11-10T00:00:00Z"},
    ]
    body = answer("midataworks", "/api/v1/datasets", items=rows, total=4, page=1, limit=200)
    lists, fake = await shaped_overview("midataworks", {"/api/v1/datasets": body})
    assert lists["datasets"] == {
        "count": 4,
        "at_least": False,
        "newest": ["b-newest", "d-second", "c-middle"],
    }
    assert [r.params for r in fake.requests if r.path == "/api/v1/versions"] == [
        {"page": "1", "limit": "3", "order": "recent"}
    ]


async def test_miserver_clusters_are_put_newest_first() -> None:
    from tests.support.scenarios import answer

    rows = [
        {"name": "alpha", "created_at": "2026-10-01T00:00:00Z"},
        {"name": "beta", "created_at": "2026-11-20T00:00:00Z"},
    ]
    body = answer(
        "miserver",
        "/api/clusters",
        success=True,
        data={"active_cluster_id": None, "clusters": rows},
        error=None,
    )
    lists, _ = await shaped_overview("miserver", {"/api/clusters": body})
    assert lists["clusters"]["newest"] == ["beta", "alpha"]


async def test_two_versions_of_one_pack_are_named_apart() -> None:
    """A miForge pack's ``name`` is shared by its versions; ``pack_id`` is ``name@version``."""
    from tests.support.scenarios import answer

    rows = [
        {"pack_id": "dlp@1", "name": "dlp", "created_at": "2026-11-01T00:00:00Z"},
        {"pack_id": "dlp@2", "name": "dlp", "created_at": "2026-11-02T00:00:00Z"},
    ]
    lists, _ = await shaped_overview(
        "miforge", {"/api/v1/packs": answer("miforge", "/api/v1/packs", packs=rows)}
    )
    assert lists["packs"]["newest"] == ["dlp@2", "dlp@1"]


def test_a_very_long_name_keeps_its_head_and_tail() -> None:
    from miassist.tools.core import NAME_MAX

    long = "hf:" + "o" * 300 + ":run-a:step-100"
    (name,) = summarise("checkpoints", {"checkpoints": [{"name": long}], "total": 1})["newest"]
    assert len(name) == NAME_MAX and "…" in name
    assert name.startswith("hf:oo") and name.endswith(":run-a:step-100")


def test_names_that_differ_only_where_shortened_are_given_whole() -> None:
    a = "hf:" + "a" * 150 + "-x-" + "b" * 150
    b = "hf:" + "a" * 150 + "-y-" + "b" * 150
    names = summarise("checkpoints", {"checkpoints": [{"name": a}, {"name": b}]})["newest"]
    assert names == [a, b]
