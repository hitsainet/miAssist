"""The own-data route (FPRD FR-003.9, 9a, 9b; FTASKS 3.1 - 3.5) over the stateful fakes."""

from __future__ import annotations

import json
from typing import Any

import pytest

from tests.playbooks.detector_probe.fakes import KEY, World, other_entries
from tests.playbooks.detector_probe.journey import journey

REPO = "evalfx/refund-messages"
ARGS: dict[str, Any] = {
    "key": KEY,
    "route": "my_labelled_data",
    "hf_repo": REPO,
    "split_train": "train",
    "split_test": "test",
    "text_column": "text",
    "label_column": "label",
    "positive_values": ["refund"],
    "nonsense_view": None,
}


def ready_world(**hub: Any) -> World:
    world = World()
    world.behaviours[KEY] = {"key": KEY, "positive_meaning": "asks for money back"}
    world.hub[REPO] = {
        "private": False,
        "gated": False,
        "licence": "cc-by-4.0",
        "bytes": 1000,
        **hub,
    }
    world.labels = {}
    return world


def downloads(j: Any) -> list[Any]:
    return [r for r in j.fakes["miworkbench"].requests if r.path == "/api/v1/datasets/download"]


def views_posted(j: Any) -> list[Any]:
    return [
        r.body
        for r in j.fakes["miworkbench"].requests
        if r.method == "POST" and r.path == "/api/v1/probe-monitors/datasets"
    ]


def test_public_dataset_is_downloaded_once_and_views_registered() -> None:
    world = ready_world()
    with journey(world=world, everyday_text_repo=REPO) as j:
        doc = j.data("miassist_detector_data", {k: v for k, v in ARGS.items() if v is not None})
        assert len(downloads(j)) == 1
        assert "access_token" not in downloads(j)[0].body
        bodies = views_posted(j)
        roles = sorted(b["role"] for b in bodies)
        assert roles == ["calibration", "eval", "everyday_text", "train"]
        for b in bodies:
            assert "access_token" not in b
        train = next(b for b in bodies if b["role"] == "train")
        assert train["behaviour"] == KEY and train["label_mapping"] == {"refund": "positive"}
        calibration = next(b for b in bodies if b["role"] == "calibration")
        assert (
            calibration["label_mapping"] == {"refund": "excluded"}
            and calibration["split"] == "test"
        )
        everyday = next(b for b in bodies if b["role"] == "everyday_text")
        assert everyday["label_mapping"] == {"*": "negative"} and "behaviour" not in everyday
        assert doc["data"]["data_ready"] is True
        assert set(doc["data"]["views"]) == {
            "train",
            "test",
            "calibration",
            "everyday_text",
            "nonsense_text",
        }
        again = j.data("miassist_detector_data", {k: v for k, v in ARGS.items() if v is not None})
        assert again["data"]["data_ready"] is True
        assert len(downloads(j)) == 1 and len(views_posted(j)) == 4, "a repeat call writes nothing"


@pytest.mark.parametrize(
    "hub,why",
    [
        ({"private": True}, "private"),
        ({"gated": "auto"}, "gated"),
        (None, "no exact match"),
        ({"bytes": 50_000_000_001}, "above the threshold"),
        ({"bytes": None}, "size unknown"),
    ],
)
def test_anything_but_public_and_moderate_is_the_operators(hub: Any, why: str) -> None:
    world = ready_world()
    if hub is None:
        world.hub.clear()
    else:
        world.hub[REPO].update(hub)
    with journey(world=world) as j:
        doc = j.data("miassist_detector_data", {k: v for k, v in ARGS.items() if v is not None})
    assert downloads(j) == [], why
    assert doc["data"]["state"] == "awaiting_download"
    assert doc["data"]["waiting"][0]["kind"] == "operator_action"
    assert "other-org" not in json.dumps(doc), "no other search item reaches a result"


def test_without_midataworks_the_download_is_the_operators() -> None:
    with journey(("miworkbench", "miserver"), world=ready_world()) as j:
        doc = j.data("miassist_detector_data", {k: v for k, v in ARGS.items() if v is not None})
    assert downloads(j) == [] and doc["data"]["state"] == "awaiting_download"


def test_three_splits_calibrate_on_the_third() -> None:
    with journey(world=ready_world(), everyday_text_repo=REPO) as j:
        j.data(
            "miassist_detector_data",
            {**{k: v for k, v in ARGS.items() if v is not None}, "split_calibration": "validation"},
        )
        calibration = next(b for b in views_posted(j) if b["role"] == "calibration")
    assert calibration["split"] == "validation"


def test_unmapped_rows_are_reported_never_hidden() -> None:
    """R1 review fix (OR1-pb-20), 2026-11-16. miWorkbench never refuses a label value the mapping
    does not name: it registers the view and counts those rows as left out
    (``counts.kinds.unmapped_label``, ``services/probe_monitor_inputs.py:327-353``). The playbook
    reports the count per view and says so; it never maps a value the person did not name."""
    world = ready_world()
    with journey(world=world, everyday_text_repo=REPO) as j:
        world.labels = {"evalfx-ds-1": ["refund", "complaint", "other"]}
        doc = j.data("miassist_detector_data", {k: v for k, v in ARGS.items() if v is not None})
        train = next(b for b in views_posted(j) if b["role"] == "train")
    assert train["label_mapping"] == {"refund": "positive"}
    assert doc["data"]["views"]["train"]["unmapped_rows"] == 200
    assert doc["data"]["views"]["train"]["rows"] == 1000
    assert doc["data"]["caution"].startswith("600 rows have a label value that no mapping names")


def test_named_everyday_view_only_never_an_unnamed_one() -> None:
    world = ready_world()
    other_entries(world)
    world.views.append(
        {"id": "evalfx-everyday-1", "name": "evalfx-everyday", "role": "everyday_text"}
    )
    with journey(world=world) as j:
        asked = j.data("miassist_detector_data", {k: v for k, v in ARGS.items() if v is not None})
        assert asked["data"]["needs"] == ["everyday_view"]
        assert "other-" not in json.dumps(asked) and "evalfx-everyday" not in json.dumps(asked)
        done = j.data(
            "miassist_detector_data",
            {
                **{k: v for k, v in ARGS.items() if v is not None},
                "everyday_view": "evalfx-everyday",
            },
        )
    assert done["data"]["views"]["everyday_text"]["id"] == "evalfx-everyday-1"
    assert "other-" not in json.dumps(done)


def test_new_nonsense_set_when_none_named() -> None:
    with journey(world=ready_world(), everyday_text_repo=REPO) as j:
        j.data("miassist_detector_data", {k: v for k, v in ARGS.items() if v is not None})
        made = [r for r in j.fakes["miworkbench"].requests if r.path.endswith("/nonsense-text")]
    assert len(made) == 1 and made[0].body["register_view"] is True and made[0].body["rows"] == 2000


def test_missing_arguments_are_named() -> None:
    with journey(world=ready_world()) as j:
        doc = j.data("miassist_detector_data", {"key": KEY, "route": "my_labelled_data"})
    assert doc["data"]["needs"] == [
        "hf_repo",
        "split_train",
        "split_test",
        "text_column",
        "label_column",
        "positive_values",
    ]
    assert j.writes() == []


def test_the_playbook_never_attempts_the_download_of_a_private_repo() -> None:
    """Two walls, each tested alone: the playbook's own check (here, by counting attempts at
    Core's call site, before Core's ``touches_hub`` refusal could hide a missing check) and Core's
    refusal (Core's Hub tests)."""
    from unittest import mock

    from miassist.adapters.base import AppClient

    attempts: list[str] = []
    real = AppClient.call

    async def spy(self: AppClient, route: Any, **kw: Any) -> Any:
        attempts.append(route.id)
        return await real(self, route, **kw)

    world = ready_world(private=True)
    with journey(world=world) as j, mock.patch.object(AppClient, "call", spy):
        j.data("miassist_detector_data", {k: v for k, v in ARGS.items() if v is not None})
    assert "midataworks.hf_search" in attempts
    assert "miworkbench.dp_dataset_download" not in attempts


def test_a_dataset_already_in_miworkbench_is_used_not_downloaded_again() -> None:
    """R1 review fix (OR1-pb-8), 2026-11-16: miWorkbench lists datasets under ``data``; the one with
    exactly this repository is found, so no second Hub download (a floor write) is made."""
    world = ready_world()
    world.datasets["evalfx-ds-9"] = {"id": "evalfx-ds-9", "hf_repo_id": REPO, "status": "ready"}
    with journey(world=world, everyday_text_repo=REPO) as j:
        j.data("miassist_detector_data", {k: v for k, v in ARGS.items() if v is not None})
        posted = views_posted(j)
    assert downloads(j) == []
    assert posted and {b["dataset_id"] for b in posted} == {"evalfx-ds-9"}
