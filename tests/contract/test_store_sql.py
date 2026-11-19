"""The SQL store on a real Postgres (001 FTASKS 6.1, 6.2, 6.4, 6.6; FPRD §5.3)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text

from miassist.store.db import Database
from miassist.store.repository import SqlStore, hash_key

REPO_ROOT = Path(__file__).resolve().parents[2]
ALLOWED = {
    "ma_preferences": {"key_hash", "guidance_level", "created_at", "updated_at"},
    "ma_playbook_progress": {
        "key_hash",
        "playbook_id",
        "subject",
        "playbook_version",
        "state",
        "updated_at",
    },
    "ma_alembic_version": {"version_num"},
}
KEY = "abcdefghijklmnopqrstuvwxyz"
OTHER = "zyxwvutsrqponmlkjihgfedcba"


@pytest.fixture
async def store(database_url: str) -> SqlStore:
    cfg = Config(str(REPO_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(REPO_ROOT / "alembic"))
    cfg.attributes["database_url"] = database_url
    await asyncio.to_thread(command.downgrade, cfg, "base")
    await asyncio.to_thread(command.upgrade, cfg, "head")
    return SqlStore(Database(database_url))


async def columns(store: SqlStore) -> dict[str, set[str]]:
    async with store.db.engine.connect() as conn:
        rows = await conn.execute(
            text(
                "SELECT table_name, column_name FROM information_schema.columns WHERE table_schema = 'public'"
            )
        )
        found: dict[str, set[str]] = {}
        for table, column in rows:
            found.setdefault(table, set()).add(column)
    return found


async def test_allowed_columns(store: SqlStore) -> None:
    assert await columns(store) == ALLOWED


async def test_level_round_trip_and_upsert(store: SqlStore) -> None:
    key_hash = hash_key(KEY)
    assert await store.level(key_hash) is None
    await store.set_level(key_hash, "expert")
    await store.set_level(key_hash, "beginner")
    assert await store.level(key_hash) == "beginner"
    with pytest.raises(ValueError):
        await store.set_level(key_hash, "wizard")


async def test_no_raw_key_stored(store: SqlStore) -> None:
    key_hash = hash_key(KEY)
    await store.set_level(key_hash, "expert")
    await store.save_progress(key_hash, "start-miforge", "", 1, {"done": ["look-around"]})
    async with store.db.engine.connect() as conn:
        for table in ("ma_preferences", "ma_playbook_progress"):
            rows = (await conn.execute(text(f"SELECT * FROM {table}"))).all()
            assert rows and all(KEY not in str(row) for row in rows)
            assert all(len(row[0]) == 64 for row in rows)


async def test_forget_scoped(store: SqlStore) -> None:
    mine, theirs = hash_key(KEY), hash_key(OTHER)
    for key_hash in (mine, theirs):
        await store.set_level(key_hash, "expert")
        await store.save_progress(key_hash, "start-miforge", "", 1, {"done": []})
    await store.forget(mine)
    assert await store.level(mine) is None and await store.progress(mine, "start-miforge") is None
    assert await store.level(theirs) == "expert" and await store.progress(theirs, "start-miforge")


async def test_sweep_by_updated_at(store: SqlStore) -> None:
    old, fresh = hash_key(KEY), hash_key(OTHER)
    await store.set_level(old, "expert")
    await store.set_level(fresh, "expert")
    async with store.db.engine.begin() as conn:
        await conn.execute(
            text(
                "UPDATE ma_preferences SET updated_at = now() - interval '200 days' WHERE key_hash = :k"
            ),
            {"k": old},
        )
    removed = await store.sweep(datetime.now(UTC), 180)
    assert removed == 1
    assert await store.level(old) is None and await store.level(fresh) == "expert"
    assert await store.sweep(datetime.now(UTC) + timedelta(seconds=1), 180) == 0
