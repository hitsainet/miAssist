"""Structured JSON logs that never carry a key, an argument value or an ``Authorization`` header
(PADR ADR-016; Foundation task 2.4).

- One JSON object per line.
- ``key_fingerprint(key_hash)`` is the first 8 hex characters of the key's SHA-256; it is logged
  in the field **``key_fp``** (R1M-25), never ``key``.
- ``DropSensitiveFields`` removes any record field named in ``DROPPED_FIELDS`` before formatting.
  It is attached to the handler, so a field passed through ``extra=`` cannot reach the output.
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime
from typing import Any, Final

#: Record fields that never reach a log line, whatever logged them (ADR-016). ``key_fp`` is
#: deliberately absent: it is the fingerprint, safe to log.
DROPPED_FIELDS: Final = frozenset({"authorization", "key", "arguments", "body"})

#: The attributes every ``LogRecord`` has; anything else on a record came from ``extra=``.
_STANDARD = frozenset(vars(logging.LogRecord("", 0, "", 0, "", None, None))) | {
    "message",
    "asctime",
    "taskName",
}


def key_fingerprint(key_hash: str) -> str:
    """The 8-character fingerprint of a key's SHA-256 hex digest, for the ``key_fp`` field."""
    return key_hash[:8]


class DropSensitiveFields(logging.Filter):
    """Delete every record attribute named in ``DROPPED_FIELDS`` (case-insensitive)."""

    def filter(self, record: logging.LogRecord) -> bool:
        for name in list(vars(record)):
            if name.lower() in DROPPED_FIELDS:
                delattr(record, name)
        return True


class JsonFormatter(logging.Formatter):
    """One JSON object per record: time, level, logger, message and the ``extra=`` fields."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "time": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for name, value in vars(record).items():
            if name not in _STANDARD and not name.startswith("_"):
                payload[name] = value
        if record.exc_info:
            payload["exc_type"] = record.exc_info[0].__name__ if record.exc_info[0] else None
        return json.dumps(payload, default=str, sort_keys=True)


def make_handler(stream: Any = None) -> logging.Handler:
    """A stream handler with the JSON formatter and the sensitive-field filter attached."""
    handler = logging.StreamHandler(stream if stream is not None else sys.stderr)
    handler.setFormatter(JsonFormatter())
    handler.addFilter(DropSensitiveFields())
    return handler


#: Libraries that log request URLs at INFO: an app URL carries path and query values taken from a
#: tool's arguments (an approval id, a dataset id), so they run at WARNING (ADR-016; 001 FR-20).
QUIET_LOGGERS: Final = ("httpx", "httpx2", "httpcore")


def configure(level: int = logging.INFO) -> None:
    """Install the JSON handler on the root logger; the MCP SDK's logger at WARNING (it logs
    call arguments at debug; ADR-016), and the HTTP clients' loggers at WARNING (they log each
    request's URL at INFO)."""
    root = logging.getLogger()
    for existing in list(root.handlers):
        root.removeHandler(existing)
    root.addHandler(make_handler())
    root.setLevel(level)
    logging.getLogger("mcp").setLevel(logging.WARNING)
    for name in QUIET_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").disabled = True
