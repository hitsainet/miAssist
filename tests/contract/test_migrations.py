"""Alembic upgrades to head and downgrades to base on a real Postgres (Foundation task 5.2)."""

from __future__ import annotations

import asyncio
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

REPO_ROOT = Path(__file__).resolve().parents[2]


def _config(url: str) -> Config:
    cfg = Config(str(REPO_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(REPO_ROOT / "alembic"))
    cfg.attributes["database_url"] = url
    return cfg


async def _tables(url: str) -> set[str]:
    engine = create_async_engine(url)
    async with engine.connect() as conn:
        rows = await conn.execute(
            text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
        )
        names = {row[0] for row in rows}
    await engine.dispose()
    return names


async def test_upgrade_then_downgrade(database_url: str) -> None:
    cfg = _config(database_url)
    await asyncio.to_thread(command.upgrade, cfg, "head")
    tables = await _tables(database_url)
    assert "ma_alembic_version" in tables
    assert all(name.startswith("ma_") for name in tables), tables
    await asyncio.to_thread(command.downgrade, cfg, "base")
    assert await _tables(database_url) <= {"ma_alembic_version"}
