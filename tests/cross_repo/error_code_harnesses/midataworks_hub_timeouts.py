"""miDataworks' Hub search and preview timeouts (ENH-013 006, FR-006.7).

Run in miDataworks' own interpreter on a ``git archive``: ``python -I -B <this> <archive backend>``.
Calls the two route functions with their Celery send stubbed to time out (the worker never answers),
and prints the code and status each raises: ``search_hf`` (``POST /api/v1/sources/hf/search``) and
``wait_for_preview``, which ``preview_hf`` (``POST /api/v1/sources/hf/preview``) awaits.
"""

import asyncio
import json
import os
import sys

from cryptography.fernet import Fernet

# Placeholder settings for IMPORTING miDataworks (never to connect), as scripts/snapshot_openapi.py.
os.environ.setdefault("SETTINGS_ENCRYPTION_KEY", Fernet.generate_key().decode())
sys.path.insert(0, sys.argv[1])

from celery.exceptions import TimeoutError as CeleryTimeout
from src.api.v1.endpoints import sources
from src.core.errors import AppError


class _Slow:
    def get(self, timeout: float) -> dict:
        raise CeleryTimeout()


class _Body:
    def model_dump(self) -> dict:
        return {}


class _Actor:
    origin = "agent"


sources.send_search = lambda *a: _Slow()
sources.send_preview = lambda *a: _Slow()
found = []
for call in (
    lambda: sources.search_hf(_Body(), _Actor()),
    lambda: sources.wait_for_preview("p", {}),
):
    try:
        asyncio.run(call())
    except AppError as exc:
        found.append([exc.code, exc.status_code])
print(json.dumps(found))
