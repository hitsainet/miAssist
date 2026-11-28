"""Shared fixtures."""

from __future__ import annotations

import pytest

from tests.support import db as test_db


@pytest.fixture
async def database_url(worker_id: str) -> str:
    """A per-worker test database URL; the database exists when the fixture returns."""
    url = test_db.worker_url(worker_id)
    await test_db.ensure_database(url, fresh=True)
    return url
