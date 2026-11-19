"""FR-002.14d: the goal behaviour must not exist before a live run; replay refuses a take whose
manifest lacks a passing fairness block."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from miassist_eval import cassette, classes, fairness, goals
from miassist_eval.classes import Refusal
from tests.support import harness


def goal() -> dict:
    return goals.load().goal("detector-refund")


def fetcher(lists: dict[tuple[str, str], list], pages: dict | None = None):
    calls = []

    async def fetch(app, route, token):
        calls.append((app, route, token))
        if pages and (app, route) in pages and token is None:
            return {"items": lists.get((app, route), [])}, "p2"
        if token == "p2":
            return {"items": pages[(app, route)]}, None
        return {"items": lists.get((app, route), [])}, None

    return fetch, calls


async def test_an_active_refund_behaviour_refuses_the_run_and_names_it() -> None:
    fetch, _ = fetcher(
        {
            ("miworkbench", "/api/v1/probe-monitors/behaviours"): [
                {"id": "b1", "name": "Refund request"}
            ]
        }
    )
    with pytest.raises(Refusal) as caught:
        await fairness.check(goal(), fetch)
    assert caught.value.cls == classes.FAIRNESS_PRECONDITION
    assert "Refund request" in caught.value.detail and "miworkbench" in caught.value.detail


async def test_an_archived_one_does_not() -> None:
    fetch, calls = fetcher(
        {
            ("miworkbench", "/api/v1/probe-monitors/behaviours"): [
                {"id": "b1", "name": "Refund request", "archived_at": "2026-11-01"}
            ]
        }
    )
    block = await fairness.check(goal(), fetch)
    assert block["passed"] is True and block["matches"] == []
    assert len(block["lists_read"]) == len(goal()["fairness"]["lists"]) == len(calls)


async def test_an_item_an_earlier_run_created_refuses() -> None:
    fetch, _ = fetcher(
        {("midataworks", "/api/v1/datasets"): [{"id": "ds-made-by-run-3", "name": "x"}]}
    )
    with pytest.raises(Refusal):
        await fairness.check(goal(), fetch, earlier_ids={"ds-made-by-run-3"})


async def test_pagination_is_followed() -> None:
    key = ("miserver", "/api/probes")
    fetch, calls = fetcher({key: []}, pages={key: [{"id": "p9", "name": "money back detector"}]})
    with pytest.raises(Refusal):
        await fairness.check(goal(), fetch)
    assert ("miserver", "/api/probes", "p2") in calls


def test_whole_words_only() -> None:
    assert (
        fairness.match_items(
            "midataworks", "/r", [{"id": "1", "name": "refundable deposits"}], ["refund"], set()
        )
        == []
    )


def test_replay_refuses_a_take_without_a_passing_fairness_block(tmp_path: Path) -> None:
    rec = harness.record(
        0, "midataworks", "GET", "/api/health", "/api/health", 200, {"status": "ok"}
    )
    take = harness.write_take(tmp_path, [rec], index=False)
    manifest_path = take.path / "MANIFEST.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["fairness"] = harness.fairness_block(passed=False)
    manifest_path.write_text(json.dumps(manifest))
    cassette.append_index(tmp_path, cassette.Take(take.path, manifest, take.cassette), "t")
    with pytest.raises(Refusal) as caught:
        cassette.load(take.path, cassette.read_index(tmp_path))
    assert caught.value.cls == classes.CASSETTE_INTEGRITY
    assert "fairness" in caught.value.detail


def test_a_passing_block_loads(tmp_path: Path) -> None:
    rec = harness.record(
        0, "midataworks", "GET", "/api/health", "/api/health", 200, {"status": "ok"}
    )
    take = harness.write_take(tmp_path, [rec])
    assert cassette.load(take.path, cassette.read_index(tmp_path)).cassette_id == take.cassette_id


def test_a_take_with_a_failing_block_is_never_written(tmp_path: Path) -> None:
    rec = harness.record(
        0, "midataworks", "GET", "/api/health", "/api/health", 200, {"status": "ok"}
    )
    with pytest.raises(ValueError, match="fairness"):
        harness.write_take(tmp_path, [rec], fairness=harness.fairness_block(passed=False))
