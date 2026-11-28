"""Tool specifications (001 FR-3, FR-18; FTID §3.9).

A ``ToolSpec`` carries everything registration needs: the name (``miassist_`` prefix, A26; its
title and description live in ``guidance/tools.yaml``), ``requires_apps`` (``"none"``, ``"any"`` or a set, read as any-of), the two
explicit hints (A13), the ``effects`` the annotation test reads (not the hints), and ``make``, which
builds the tool function from the process's dependencies.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from miassist.guidance.loader import Guidance
    from miassist.playbooks.registry import PlaybookRegistry
    from miassist.runtime import Runtime

#: What a tool does, for AR-3/AR-4 (read from the spec, never inferred from the hints).
Effect = Literal["store_read", "store_write", "store_delete", "app_read", "app_write", "none"]


@dataclass
class Deps:
    runtime: Runtime
    guidance: Guidance
    extras: dict[str, Any] = field(default_factory=dict)
    #: The playbook registry, loaded by ``build_server`` (001 FR-5, AC-5.4).
    playbooks: PlaybookRegistry | None = None
    #: Each registered tool's own function (unaudited), for in-process calls by the stateless
    #: start-here status provider (A25). Filled by ``build_server``.
    tool_functions: dict[str, Callable[..., Awaitable[Any]]] = field(default_factory=dict)


@dataclass(frozen=True)
class ToolSpec:
    name: str
    requires_apps: Literal["none", "any"] | frozenset[str]
    read_only: bool
    destructive: bool
    effects: frozenset[Effect]
    make: Callable[[Deps], Callable[..., Awaitable[Any]]]

    def offered(self, installed: frozenset[str]) -> bool:
        if self.requires_apps == "none":
            return True
        if self.requires_apps == "any":
            return bool(installed)
        return bool(self.requires_apps & installed)
