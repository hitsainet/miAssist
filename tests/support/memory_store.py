"""An in-memory store with the SQL store's API, for tool tests (the SQL store has its own tests)."""

from __future__ import annotations

from datetime import datetime
from typing import Any


class MemoryStore:
    def __init__(self, *, down: bool = False) -> None:
        self.levels: dict[str, str] = {}
        self.progresses: dict[tuple[str, str, str], dict[str, Any]] = {}
        self.down = down
        self.write_calls = 0
        self.read_calls = 0

    def _check(self) -> None:
        if self.down:
            raise ConnectionError("store down")

    async def level(self, key_hash: str) -> str | None:
        self.read_calls += 1
        self._check()
        return self.levels.get(key_hash)

    async def set_level(self, key_hash: str, level: str) -> None:
        self.write_calls += 1
        self._check()
        self.levels[key_hash] = level

    async def progress(
        self, key_hash: str, playbook_id: str, subject: str = ""
    ) -> dict[str, Any] | None:
        self.read_calls += 1
        self._check()
        return self.progresses.get((key_hash, playbook_id, subject))

    async def save_progress(
        self, key_hash: str, playbook_id: str, subject: str, version: int, state: dict[str, Any]
    ) -> None:
        self.write_calls += 1
        self._check()
        self.progresses[(key_hash, playbook_id, subject)] = {
            "playbook_version": version,
            "state": state,
        }

    async def forget(self, key_hash: str) -> None:
        self.write_calls += 1
        self._check()
        self.levels.pop(key_hash, None)
        for key in [k for k in self.progresses if k[0] == key_hash]:
            del self.progresses[key]

    async def sweep(self, now: datetime, retention_days: int) -> int:
        return 0
