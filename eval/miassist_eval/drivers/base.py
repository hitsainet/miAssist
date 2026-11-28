"""The driver protocol (FTID §3.9)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, ClassVar


@dataclass
class ClientInfo:
    name: str
    version: str
    model_requested: str | None = None
    model_served: str | None = None
    digest: str | None = None


@dataclass
class Turn:
    ended: bool
    final_message: str
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    usage: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


class Driver:
    """A client the harness drives. Subclasses set ``name`` and ``paid``."""

    name: ClassVar[str] = "base"
    paid: ClassVar[bool] = False

    def preflight(self, cfg: dict[str, Any]) -> ClientInfo:
        raise NotImplementedError
