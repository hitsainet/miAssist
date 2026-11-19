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
