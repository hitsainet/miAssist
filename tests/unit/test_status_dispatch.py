"""``miassist_status(playbook=...)`` dispatches to the playbook's status provider (001 FR-23,
AC-23.3, AC-23.4; FTASKS 11.5): exactly once, with ``(key_hash, subject)``, its document validated
against ``$defs.playbook_status``; an unknown or not-offered id answers the calm absent answer."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from miassist.guidance.loader import Guidance
from miassist.playbooks import status as status_module
from tests.support.app_factory import client
from tests.support.fake_apps import all_fakes
from tests.support.http_mcp import call_tool
from tests.support.playbook_copies import (
    FIXTURE_WORDS,
    copy_guidance,
    fixture_definition,
    write_definition,
    write_words,
)

KEY = "abcdefghijklmnopqrstuvwxyz"
FORBIDDEN = ("error", "warning", "fail", "refus", "cannot", "unable")
URLS = {
    f"{a}_url": f"http://{a}.test" for a in ("miworkbench", "miserver", "midataworks", "miforge")
}


class Recording:
    def __init__(self, document: dict[str, Any] | None = None) -> None:
        self.calls: list[tuple[str | None, str]] = []
        self.document = document

    async def __call__(
        self, deps: Any, playbook: Any, key_hash: str | None, subject: str
    ) -> dict[str, Any]:
        self.calls.append((key_hash, subject))
        if self.document is not None:
            return self.document
        return {
            "playbook_id": playbook.id,
            "playbook_version": playbook.version,
            "finished": False,
            "where": "two",
            "done": ["one"],
            "next": {"tool": "miassist_guide", "args": {"topic": "playbooks"}, "why": "Step two."},
            "waiting": [{"kind": "operator_action", "detail": "The operator arms it in the app."}],
            "expected": "The second step.",
            "not_in_this_installation": [],
        }


@pytest.fixture
def fixture_setup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Guidance, Path]:
    root = copy_guidance(tmp_path)
    write_words(root, "fixture-pb", FIXTURE_WORDS)
    folder = tmp_path / "definitions"
    folder.mkdir()
    write_definition(folder, fixture_definition())
    return Guidance(root), folder


def _status(
    words: Guidance, folder: Path, provider: Any, monkeypatch: pytest.MonkeyPatch, **args: Any
) -> dict[str, Any]:
    monkeypatch.setitem(status_module.PROVIDERS, "fixture-pb", provider)
    fakes = all_fakes()
    with client(
        transports={a: f.transport() for a, f in fakes.items()},
        apps="miforge",
        guidance=words,
        definitions=folder,
        **URLS,
    ) as test_client:
        return call_tool(test_client, f"/p/{KEY}/mcp", "miassist_status", args)


def test_provider_called_once(
    fixture_setup: tuple[Guidance, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    words, folder = fixture_setup
    provider = Recording()
    result = _status(
        words, folder, provider, monkeypatch, playbook="fixture-pb", subject="behaviour-1"
    )
    assert provider.calls == [(hashlib.sha256(KEY.encode()).hexdigest(), "behaviour-1")]
    assert result["isError"] is False
    data = result["structuredContent"]["data"]
    assert data["playbook"]["where"] == "two" and data["playbook"]["done"] == ["one"]
    assert result["structuredContent"]["next_steps"] == [data["playbook"]["next"]]


def test_subject_defaults_to_empty(
    fixture_setup: tuple[Guidance, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    words, folder = fixture_setup
    provider = Recording()
    _status(words, folder, provider, monkeypatch, playbook="fixture-pb")
    assert [subject for _, subject in provider.calls] == [""]


def test_invalid_document_is_refused(
    fixture_setup: tuple[Guidance, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    words, folder = fixture_setup
    provider = Recording({"playbook_id": "fixture-pb", "finished": "maybe"})
    result = _status(words, folder, provider, monkeypatch, playbook="fixture-pb")
    assert result["isError"] is True
    assert result["content"][0]["text"].startswith("playbook_status_invalid: ")


def test_no_playbook_no_dispatch(
    fixture_setup: tuple[Guidance, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    words, folder = fixture_setup
    provider = Recording()
    result = _status(words, folder, provider, monkeypatch)
    assert provider.calls == []
    assert result["structuredContent"]["data"]["playbooks"] == [
        {"id": "fixture-pb", "title": "Fixture playbook"}
    ]


@pytest.mark.parametrize("playbook_id", ["no-such-playbook", "start-miserver"])
def test_unknown_playbook_is_calm(playbook_id: str) -> None:
    fakes = all_fakes()
    with client(
        transports={a: f.transport() for a, f in fakes.items()}, apps="miforge", **URLS
    ) as test_client:
        result = call_tool(test_client, "/mcp", "miassist_status", {"playbook": playbook_id})
    assert result["isError"] is False
    structured = result["structuredContent"]
    assert "unavailable" not in structured
    data = structured["data"]
    assert data["offered"] is False and data["playbook"] is None
    assert data["needs"] == ([] if playbook_id == "no-such-playbook" else ["miserver"])
    text = " ".join(
        [json.dumps(structured)] + [c.get("text", "") for c in result["content"]]
    ).lower()
    for word in FORBIDDEN:
        assert word not in text, word
    assert structured["next_steps"] == [
        {"tool": "miassist_overview", "args": {"app": "miforge"}, "why": "Start here: miForge"}
    ]
