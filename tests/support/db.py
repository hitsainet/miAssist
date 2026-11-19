"""The test database (Foundation task 5.2). Never the production one.

``MIASSIST_TEST_DATABASE_URL`` (an asyncpg URL) names the server; by default the local test-only
container on 127.0.0.1:55450 with its test-only password. Each xdist worker gets its own database,
``<name>_<worker>``, created on first use. When the server is unreachable the tests skip loudly,
unless ``MIASSIST_REQUIRE_TEST_DATABASE=1`` (CI sets it), when they fail.
"""

from __future__ import annotations

import os
from urllib.parse import urlsplit, urlunsplit

import pytest

DEFAULT_URL = "postgresql+asyncpg://postgres:miassist-test-only@127.0.0.1:55450/miassist_test"


def base_url() -> str:
    return os.environ.get("MIASSIST_TEST_DATABASE_URL", DEFAULT_URL)


def worker_url(worker_id: str) -> str:
    parts = urlsplit(base_url())
    name = parts.path.lstrip("/") or "miassist_test"
    if worker_id not in ("", "master"):
        name = f"{name}_{worker_id}"
    return urlunsplit(parts._replace(path="/" + name))


async def ensure_database(url: str, *, fresh: bool = False) -> None:
    """Create the database ``url`` names if it does not exist; ``fresh`` drops it first, so a run
    never inherits a schema version another checkout's migrations left behind."""
    import asyncpg

    parts = urlsplit(url)
    name = parts.path.lstrip("/")
    admin = urlunsplit(parts._replace(scheme="postgresql", path="/postgres"))
    try:
        conn = await asyncpg.connect(admin, timeout=3)
    except Exception as exc:  # unreachable server
        message = f"the test database server is unreachable ({type(exc).__name__})"
        if os.environ.get("MIASSIST_REQUIRE_TEST_DATABASE") == "1":
            pytest.fail(message)
        pytest.skip(message)
    try:
        if fresh:
            await conn.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
        exists = await conn.fetchval("SELECT 1 FROM pg_database WHERE datname = $1", name)
        if not exists:
            await conn.execute(f'CREATE DATABASE "{name}"')
    finally:
        await conn.close()
