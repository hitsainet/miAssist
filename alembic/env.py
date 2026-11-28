"""Alembic environment (PADR ADR-004; Foundation task 5.2). Async, over the settings' URL."""

from __future__ import annotations

import asyncio

from alembic import context
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

import miassist.store.models_registry  # noqa: F401 - registers every model on Base.metadata
from miassist.config import MiAssistSettings
from miassist.store.db import Base

target_metadata = Base.metadata
VERSION_TABLE = "ma_alembic_version"


def _url() -> str:
    configured = context.config.attributes.get("database_url")
    return str(configured) if configured else MiAssistSettings().database_url


def run_migrations_offline() -> None:
    context.configure(
        url=_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        version_table=VERSION_TABLE,
    )
    with context.begin_transaction():
        context.run_migrations()


def _run(connection: Connection) -> None:
    context.configure(
        connection=connection, target_metadata=target_metadata, version_table=VERSION_TABLE
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    engine = create_async_engine(_url())
    async with engine.connect() as connection:
        await connection.run_sync(_run)
    await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
