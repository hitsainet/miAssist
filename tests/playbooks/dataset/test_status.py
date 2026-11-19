"""The dataset playbook's status (004 FTASKS 1.2, 1.5; FPRD FR-004.19, FR-004.19a; FTDD §7).

Status is derived from miDataworks alone: per state it yields ``where``, ``next.tool`` and
``waiting``; deleting the progress record changes none of them; Core's ``evaluate_done_when`` is
called exactly once per step per status call (patched and counted).
"""

from __future__ import annotations

from typing import Any

import pytest

from miassist.guidance.loader import Guidance
from miassist.playbooks.dataset import status as status_module
from miassist.playbooks.registry import PlaybookError
from tests.playbooks.dataset.fake import Dataworks
from tests.playbooks.dataset.support import Session
from tests.support.memory_store import MemoryStore
from tests.support.playbook_copies import copy_guidance


def built(**kw: Any) -> tuple[Dataworks, str]:
    dw_ = Dataworks(**kw)
    seeded = dw_.seed_built()
    return dw_, seeded["dataset"]["name"]


async def status_of(dw_: Dataworks, subject: str, store: Any = None) -> dict[str, Any]:
    async with Session(dw_, store=store) as s:
        return await s.status(subject)


async def test_nothing_chosen() -> None:
    got = await status_of(Dataworks(), "")
    assert got["where"] == "find" and got["next"]["tool"] == "miassist_dataset_find"
    assert got["waiting"] == [] and got["done"] == []


async def test_unknown_dataset_reads_as_nothing_chosen() -> None:
    got = await status_of(Dataworks(), "no-such-dataset")
    assert got["where"] == "find" and got["done"] == []


async def test_version_ready_waits_for_the_operators_check_run() -> None:
    dw_, name = built()
    got = await status_of(dw_, name)
    assert got["done"] == ["find", "build"] and got["where"] == "check"
    assert got["waiting"][0]["kind"] == "operator_action" and got["next"] is None
    assert "Version 1 is built with 48000 rows." == got["expected"]


async def test_publish_waiting_carries_the_approval() -> None:
    dw_, name = built()
    version = next(iter(dw_.versions.values()))
    dw_._approve_later("hub_push", {"body": {"version_id": version["id"], "repo_id": "a/b"}})
    got = await status_of(dw_, name)
    assert got["where"] == "check"
    approval = got["waiting"][0]["approval"]
    assert got["waiting"][0]["kind"] == "approval"
    assert approval["decide_in"] == "midataworks" and approval["status"] == "pending"
    assert approval["then"] == "server_runs"


async def test_published_is_finished() -> None:
    dw_, name = built(publish_status="published")
    version = next(iter(dw_.versions.values()))
    dw_._approve_later(
        "hub_push",
        {"body": {"version_id": version["id"], "repo_id": "a/b", "visibility": "private"}},
    )
    dw_.decide("executed")
    got = await status_of(dw_, name)
    assert got["finished"] is True and got["where"] is None and got["next"] is None
    assert got["done"] == ["find", "build", "check", "publish"]


async def test_publishing_is_a_job_wait() -> None:
    dw_, name = built(publish_status="uploading")
    version = next(iter(dw_.versions.values()))
    dw_._approve_later(
        "hub_push",
        {"body": {"version_id": version["id"], "repo_id": "a/b", "visibility": "private"}},
    )
    dw_.decide("executing")
    got = await status_of(dw_, name)
    assert got["where"] == "publish" and got["waiting"][0]["kind"] == "job"


async def test_rejected_says_so() -> None:
    dw_, name = built()
    version = next(iter(dw_.versions.values()))
    dw_._approve_later("hub_push", {"body": {"version_id": version["id"], "repo_id": "a/b"}})
    dw_.decide("rejected", "not this one")
    got = await status_of(dw_, name)
    assert got["expected"] == "The operator turned the publish down."


async def test_deleting_the_progress_record_changes_nothing() -> None:
    dw_, name = built()
    store = MemoryStore()
    await store.save_progress("k" * 64, "dataset", name, 1, {"chosen": {"check_run_id": "x"}})
    with_record = await status_of(dw_, name, store)
    await store.forget("k" * 64)
    without = await status_of(dw_, name, store)
    assert with_record == without


async def test_down_midataworks_is_calm() -> None:
    dw_, name = built()
    async with Session(dw_) as s:
        s.deps.runtime.detector.mark_unreachable("midataworks", "connection refused")
        result = await s.call("miassist_status", {"playbook": "dataset", "subject": name})
    assert not result.is_error


async def test_evaluate_done_when_called_once_per_step(monkeypatch: pytest.MonkeyPatch) -> None:
    """FR-004.19a: Core's predicate, counted; an inline check instead would leave the count 0."""
    from miassist.playbooks import done_when

    calls: list[Any] = []

    def counted(predicate: Any, value: Any) -> bool:
        calls.append(predicate)
        return done_when.evaluate_done_when(predicate, value)

    monkeypatch.setattr(status_module, "evaluate_done_when", counted)
    dw_, name = built()
    got = await status_of(dw_, name)
    assert len(calls) == 4
    assert [c.pointer for c in calls] == [
        "/candidates/0",
        "/version_ready",
        "/checks_complete",
        "/publish_status",
    ]
    assert got["done"] == ["find", "build"]


def test_a_deleted_words_key_refuses_start_naming_it(tmp_path: Any) -> None:
    """1.2's negative control as a test: every key the definition names must resolve."""
    folder = copy_guidance(tmp_path)
    words = folder / "playbooks" / "dataset.yaml"
    text = words.read_text()
    words.write_text(text.replace("  dataset.check.done:", "  dataset.check.gone:"))
    from tests.support.servers import make_server

    with pytest.raises(PlaybookError, match=r"dataset\.check\.done"):
        make_server(("midataworks",), None, words=Guidance(folder))
