"""The driver registry (FR-002.18, FR-002.19; FTID §3.9). ``suite.build()`` reads ``REGISTRY``;
a suite planning a client whose registration is missing refuses to start."""

from __future__ import annotations

from miassist_eval.drivers.base import Driver
from miassist_eval.drivers.claude_code import ClaudeCodeDriver
from miassist_eval.drivers.open_webui import OpenWebUIDriver
from miassist_eval.drivers.scripted import ScriptedDriver

REGISTRY: dict[str, type[Driver]] = {}


def register(cls: type[Driver]) -> type[Driver]:
    REGISTRY[cls.name] = cls
    return cls


register(ScriptedDriver)
register(ClaudeCodeDriver)
register(OpenWebUIDriver)
