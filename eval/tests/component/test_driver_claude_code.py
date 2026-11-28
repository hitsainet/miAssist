"""FR-002.18, FR-002.20, FR-002.27 against a HAND-WRITTEN stand-in for Claude Code's stream-json
(tests/fixtures/clients/claude_code/hand-written/). Spike FTASKS 1.2 replaces it with the pinned
version's captured output; until then the field names are unverified (FTID §3.10)."""

from __future__ import annotations

from pathlib import Path

import pytest

from miassist_eval import budget, classes, schemas
from miassist_eval.classes import Refusal
from miassist_eval.drivers import claude_code as cc
from miassist_eval.drivers.base import ClientInfo

FIXTURE = (
    Path(__file__).resolve().parents[1] / "fixtures/clients/claude_code/hand-written/stream.jsonl"
)


def parsed() -> cc.Parsed:
    return cc.parse(FIXTURE.read_text().splitlines())


def test_versions_model_and_servers_are_parsed() -> None:
    p = parsed()
    assert p.version == "0.0.0-hand-written" and p.model_served == "model-x"
    assert p.servers == {"under_test": "connected"}
    assert [t["name"] for t in p.tool_uses] == ["mcp__under_test__list_sets"]
    assert p.session_id == "sess-1" and p.turns == 3 and p.cost_usd == 0.01


def test_one_mcp_server_and_the_disallow_list() -> None:
    argv = cc.command("hi", Path("/tmp/mcp.json"), "model-x", ["under_test"])
    assert "--strict-mcp-config" in argv
    assert argv[argv.index("--allowedTools") + 1] == "mcp__under_test"
    for tool in ("Bash", "Read", "WebFetch", "Task"):
        assert tool in argv[argv.index("--disallowedTools") :]


def test_resume_carries_the_session() -> None:
    argv = cc.command("That sounds fine.", Path("/m.json"), "model-x", ["u"], resume="sess-1")
    assert argv[-2:] == ["--resume", "sess-1"]


def test_the_environment_is_a_clean_room(tmp_path: Path) -> None:
    env = cc.clean_env(tmp_path, "ANTHROPIC_API_KEY", "k-value")
    assert env == {
        "HOME": str(tmp_path),
        "PATH": "/usr/local/bin:/usr/bin:/bin",
        "ANTHROPIC_API_KEY": "k-value",
    }


def test_an_unconnected_server_is_invalid() -> None:
    p = parsed()
    assert cc.connected(p, ["under_test"]) is None
    p.servers["under_test"] = "failed"
    assert cc.connected(p, ["under_test"]) == classes.SERVER_NOT_CONNECTED


def test_unreported_tokens_are_null_with_a_reason_never_zero() -> None:
    t = cc.tokens(parsed())
    assert t["input"] == 120 and t["cache_write"] is None
    assert t["null_reason"]["cache_write"] == "not reported by the client"


def test_the_version_capture_feeds_the_record() -> None:
    """C-5: without the capture the record's client version is empty and the schema refuses it."""
    info = cc.ClaudeCodeDriver.capture_versions(parsed(), ClientInfo("claude_code", ""))
    assert info.version == "0.0.0-hand-written" and info.model_served == "model-x"
    run = {"client": {"name": info.name, "version": info.version}}
    assert (
        schemas.schema("eval-run")["properties"]["client"]["properties"]["version"]["minLength"]
        == 1
    )
    assert run["client"]["version"]


def test_the_driver_refuses_under_ci(monkeypatch) -> None:
    monkeypatch.setenv("CI", "true")
    assert budget.in_ci()
    with pytest.raises(Refusal) as caught:
        cc.ClaudeCodeDriver().preflight({})
    assert caught.value.cls == classes.CI_REFUSED
