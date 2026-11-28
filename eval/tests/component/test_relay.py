"""FR-002.40: one WAITING.txt line per new pending approval, named as evaluation traffic; the
"approved" reply only after a read shows it decided, once."""

from __future__ import annotations

from pathlib import Path

from miassist_eval.relay import Relay


async def test_one_line_then_one_reply_after_decided(tmp_path: Path) -> None:
    states = iter(["pending", "pending", "approved", "approved"])
    said = []

    async def read(app, route):
        assert route == "/api/v1/mcp/approvals"
        return [
            {"id": "a1", "status": next(states), "tool_name": "evaluate_probe_monitor"},
            {"id": "operator-own", "status": "pending"},
        ]

    relay = Relay("r1", tmp_path / "WAITING.txt", filed={"a1"}, say=said.append)
    assert await relay.poll(read, ["miworkbench"]) == []
    assert await relay.poll(read, ["miworkbench"]) == []
    assert await relay.poll(read, ["miworkbench"]) == ["a1"]
    assert await relay.poll(read, ["miworkbench"]) == []
    lines = (tmp_path / "WAITING.txt").read_text().splitlines()
    assert len(lines) == 1 and "EVALUATION TRAFFIC" in lines[0] and "a1" in lines[0]
    assert "operator-own" not in lines[0]


def test_a_handoff_gets_a_line(tmp_path: Path) -> None:
    relay = Relay("r1", tmp_path / "WAITING.txt", filed=set(), say=lambda s: None)
    relay.handoff("arm probe evalfx-p")
    assert "miServer" in (tmp_path / "WAITING.txt").read_text()
