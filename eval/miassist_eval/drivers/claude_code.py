"""The Claude Code driver (FR-002.18, FR-002.20, FR-002.27; FTID §3.10).

FLAGS AND EVENT FIELDS ARE UNVERIFIED until spike FTASKS 1.2 (operator, by hand, one paid stub run;
M13). Parsing is written against ``tests/fixtures/clients/claude_code/hand-written/``, which is a
hand-written stand-in and says so; 1.2 replaces it with the pinned version's captured output. The
driver refuses to start under CI (M13) and never reads a key from a file the harness writes.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, ClassVar

from miassist_eval import budget, classes
from miassist_eval.classes import Refusal
from miassist_eval.drivers.base import ClientInfo, Driver

DISALLOWED = (
    "Bash",
    "Edit",
    "Write",
    "Read",
    "Glob",
    "Grep",
    "WebFetch",
    "WebSearch",
    "NotebookEdit",
    "Task",
    "TodoWrite",
)
MAX_TURNS = 80


def command(
    phrasing: str, mcp_config: Path, model: str, servers: list[str], resume: str | None = None
) -> list[str]:
    argv = [
        "claude",
        "-p",
        phrasing,
        "--output-format",
        "stream-json",
        "--verbose",
        "--mcp-config",
        str(mcp_config),
        "--strict-mcp-config",
        "--model",
        model,
        "--max-turns",
        str(MAX_TURNS),
        "--allowedTools",
        *[f"mcp__{s}" for s in servers],
        "--disallowedTools",
        *DISALLOWED,
    ]
    if resume:
        argv += ["--resume", resume]
    return argv


def clean_env(home: Path, key_env: str, key_value: str) -> dict[str, str]:
    """Empty HOME, the provider key from the operator's own environment, nothing else inherited."""
    return {"HOME": str(home), "PATH": "/usr/local/bin:/usr/bin:/bin", key_env: key_value}


@dataclass
class Parsed:
    version: str | None = None
    model_served: str | None = None
    servers: dict[str, str] = field(default_factory=dict)
    tools: list[str] = field(default_factory=list)
    tool_uses: list[dict[str, Any]] = field(default_factory=list)
    final_message: str = ""
    usage: dict[str, Any] = field(default_factory=dict)
    cost_usd: float | None = None
    turns: int | None = None
    session_id: str | None = None
    is_error: bool = False
    discovery_calls: int = 0


def parse(lines: list[str]) -> Parsed:
    """Parse the stream-json events (field names per the spike's capture; unverified until 1.2)."""
    out = Parsed()
    for raw in lines:
        if not raw.strip():
            continue
        event = json.loads(raw)
        kind = event.get("type")
        if kind == "system" and event.get("subtype") == "init":
            out.version = event.get("claude_code_version") or out.version
            out.model_served = event.get("model")
            out.servers = {s["name"]: s.get("status", "") for s in event.get("mcp_servers", [])}
            out.tools = list(event.get("tools", []))
            out.session_id = event.get("session_id")
        elif kind == "assistant":
            for block in event.get("message", {}).get("content", []):
                if block.get("type") == "tool_use":
                    if str(block.get("name", "")).startswith("mcp__"):
                        out.tool_uses.append({"name": block["name"], "input": block.get("input")})
                    else:
                        out.discovery_calls += 1
                elif block.get("type") == "text":
                    out.final_message = block.get("text", "")
        elif kind == "result":
            out.usage = dict(event.get("usage") or {})
            out.cost_usd = event.get("total_cost_usd")
            out.turns = event.get("num_turns")
            out.session_id = event.get("session_id") or out.session_id
            out.is_error = bool(event.get("is_error"))
            if event.get("result"):
                out.final_message = str(event["result"])
    return out


def tokens(parsed: Parsed) -> dict[str, Any]:
    """FR-002.25: a figure the client does not report is null with the reason, never 0."""
    names = {
        "input": "input_tokens",
        "output": "output_tokens",
        "cache_read": "cache_read_input_tokens",
        "cache_write": "cache_creation_input_tokens",
    }
    out: dict[str, Any] = {"reported": {}, "null_reason": {}}
    for mine, theirs in names.items():
        if theirs in parsed.usage:
            out[mine] = int(parsed.usage[theirs])
            out["reported"][mine] = True
        else:
            out[mine] = None
            out["reported"][mine] = False
            out["null_reason"][mine] = "not reported by the client"
    return out


def connected(parsed: Parsed, servers: list[str]) -> str | None:
    """``server_not_connected`` unless every server under test reports connected (FR-002.21)."""
    for s in servers:
        if parsed.servers.get(s) != "connected":
            return classes.SERVER_NOT_CONNECTED
    return None


class ClaudeCodeDriver(Driver):
    name: ClassVar[str] = "claude_code"
    paid: ClassVar[bool] = True

    def preflight(self, cfg: dict[str, Any]) -> ClientInfo:
        if budget.in_ci():
            raise Refusal(classes.CI_REFUSED, "Claude Code never runs in CI (M13)")
        return ClientInfo(
            name=self.name, version=str(cfg.get("version", "")), model_requested=cfg.get("model")
        )

    @staticmethod
    def capture_versions(parsed: Parsed, info: ClientInfo) -> ClientInfo:
        """FR-002.27: the version and the served model the CLIENT reported (C-5)."""
        info.version = parsed.version or ""
        info.model_served = parsed.model_served
        return info
