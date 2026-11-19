"""Canonical JSON and sha256 for every internal hash (TD-4; FR-002.4, FR-002.13)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


def dumps(obj: Any) -> str:
    """Sorted keys, compact separators, UTF-8 text (TD-4). Never leaves miAssist."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256(obj: Any) -> str:
    """sha256 of the canonical JSON of ``obj``."""
    return sha256_bytes(dumps(obj).encode("utf-8"))


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())
