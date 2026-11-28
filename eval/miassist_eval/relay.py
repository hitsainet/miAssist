"""The approval relay (FR-002.40; FTID §3.14; suite memory ``approval-relay-pattern``).

Every 15 s it reads each app's approval queue through the recorder (read routes only), filtered to
approvals filed during the run. A new pending one appends a line to ``WAITING.txt`` and the console
naming it as **evaluation traffic** (M11's residual risk); an operator hand-off gets a line too. The
fixed "approved" reply is sent once, only after a status read shows the approval decided.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

QUEUES = {
    "miworkbench": "/api/v1/mcp/approvals",  # mcp_approvals.py:363
    "midataworks": "/api/v1/approvals",  # approvals.py:62
    "miforge": "/api/v1/approvals",  # approvals.py:36
    "miserver": "/api/approvals",  # management/approvals.py:37,57
}
WHERE = {
    "miworkbench": "miWorkbench's Approvals page",
    "midataworks": "miDataworks' Approvals page",
    "miforge": "miForge's Approvals view",
    "miserver": "miServer's Approvals page",
}
DECIDED = frozenset(
    {"approved", "executing", "executed", "denied", "rejected", "expired", "failed", "consumed"}
)
INTERVAL_S = 15
#: ``(app, route) -> answer body`` through the recorder.
Read = Callable[[str, str], Awaitable[Any]]


def _items(body: Any) -> list[Mapping[str, Any]]:
    if isinstance(body, Mapping):
        for key in ("items", "approvals", "data"):
            if key in body:
                return _items(body[key])
        return []
    return [i for i in body if isinstance(i, Mapping)] if isinstance(body, list) else []


@dataclass
class Relay:
    run_id: str
    waiting: Path
    filed: set[str]
    say: Callable[[str], None] = print
    seen: set[str] = field(default_factory=set)
    replied: set[str] = field(default_factory=set)

    def _line(self, text: str) -> None:
        self.waiting.parent.mkdir(parents=True, exist_ok=True)
        with self.waiting.open("a", encoding="utf-8") as fh:
            fh.write(text + "\n")
        self.say(text)

    def handoff(self, what: str) -> None:
        self._line(
            f"[run {self.run_id}] EVALUATION TRAFFIC: operator hand-off: {what} "
            "(do it in miServer, then the run continues)"
        )

    async def poll(self, read: Read, apps: Iterable[str]) -> list[str]:
        """One pass: returns the approval ids decided since the last pass (each once)."""
        decided = []
        for app in apps:
            for item in _items(await read(app, QUEUES[app])):
                aid = str(item.get("id") or item.get("request_id") or "")
                if aid not in self.filed:
                    continue
                status = str(item.get("status", ""))
                if status == "pending" and aid not in self.seen:
                    self.seen.add(aid)
                    summary = item.get("summary") or item.get("tool_name") or item.get("action")
                    self._line(
                        f"[run {self.run_id}] EVALUATION TRAFFIC: {app} approval {aid} "
                        f"({summary}) is waiting; decide it in {WHERE[app]}"
                    )
                elif status in DECIDED and aid not in self.replied:
                    self.replied.add(aid)
                    decided.append(aid)
        return decided
