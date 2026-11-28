# Origin: miForge (Onegaishimas/miForge) backend/src/mcp_server/server.py @ e4251e4 (wrap_tool_with_audit).
# Mode: adapt (docs/REUSE.md). Changed: argument NAMES only, the key as its fingerprint (key_fp).
"""One log line per tool call (PADR ADR-016; 001 FR-20): tool, outcome, duration, the apps called
and the key fingerprint (``key_fp``). Never argument values, result bodies or the key."""

from __future__ import annotations

import functools
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

from mcp.types import CallToolResult

from miassist.logging import key_fingerprint

_log = logging.getLogger("miassist.audit")


def outcome_of(result: Any) -> str:
    if isinstance(result, CallToolResult):
        if result.is_error:
            text = (
                result.content[0].text
                if result.content and hasattr(result.content[0], "text")
                else ""
            )
            return "error:" + (text.split(":", 1)[0] if text else "unknown")
        data = result.structured_content or {}
        if "unavailable" in data:
            return "unavailable"
        if "approval" in data:
            return "pending"
    return "ok"


def audited(
    name: str, fn: Callable[..., Awaitable[Any]], key_hash: Callable[[dict[str, Any]], str | None]
) -> Callable[..., Awaitable[Any]]:
    @functools.wraps(fn)
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        start = time.monotonic()
        outcome = "error:internal"
        try:
            result = await fn(*args, **kwargs)
            outcome = outcome_of(result)
            return result
        finally:
            hashed = key_hash(kwargs)
            _log.info(
                "tool call",
                extra={
                    "event": "tool",
                    "tool": name,
                    "outcome": outcome,
                    "ms": round((time.monotonic() - start) * 1000, 1),
                    "argument_names": sorted(k for k in kwargs if k != "ctx"),
                    "key_fp": key_fingerprint(hashed) if hashed else None,
                },
            )

    return wrapper
