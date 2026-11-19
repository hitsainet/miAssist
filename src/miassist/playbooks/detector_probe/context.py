"""One tool call's context: the person's level and key, the installed apps, the clients and the
progress record (003 FTDD §6; FPRD §5.2). Progress is read and written only on a personal link,
and written only after an app write succeeded (FTDD §4)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from miassist.adapters.base import AppClient
from miassist.guidance.loader import Guidance
from miassist.playbooks._shared import calm
from miassist.server.specs import Deps
from miassist.store.degrading import StoreUnavailable

PLAYBOOK = "detector-probe"
VERSION = 1


@dataclass
class Ctx:
    deps: Deps
    mcp: Any
    key_hash: str | None
    level: str
    chosen: dict[str, Any] = field(default_factory=dict)

    @property
    def guidance(self) -> Guidance:
        return self.deps.guidance

    @property
    def installed(self) -> frozenset[str]:
        return frozenset(self.deps.runtime.installed)

    def has(self, app: str) -> bool:
        return app in self.installed

    def client(self, app: str) -> AppClient:
        return self.deps.runtime.clients[app]

    def say(self, key: str, **slots: object) -> str:
        return calm.words(self.guidance, PLAYBOOK, key, **slots)

    def missing(self) -> list[str]:
        return [a for a in ("miworkbench", "miserver", "midataworks") if not self.has(a)]

    async def load(self, subject: str) -> None:
        if self.key_hash is None:
            return
        record = await self.deps.runtime.store.progress(self.key_hash, PLAYBOOK, subject)
        self.chosen = dict((record or {}).get("state") or {})

    async def remember(self, subject: str, **changes: Any) -> bool:
        """Merge ``changes`` into the progress record (ids and choices only, FPRD §5.2)."""
        for name, value in changes.items():
            if isinstance(value, dict) and isinstance(self.chosen.get(name), dict):
                self.chosen[name] = {**self.chosen[name], **value}
            else:
                self.chosen[name] = value
        if self.key_hash is None:
            return False
        try:
            await self.deps.runtime.store.save_progress(
                self.key_hash, PLAYBOOK, subject, VERSION, self.chosen
            )
        except StoreUnavailable:
            return False
        return True
