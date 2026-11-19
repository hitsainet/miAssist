"""The database layer (PADR ADR-004; Foundation task 5.1).

An async SQLAlchemy 2 engine over asyncpg, a session factory, a declarative ``Base`` whose naming
convention prefixes every constraint and index with ``ma_``, and ``ping()`` for ``/health``.
Tables arrive with feature 001 (its task 6.0); every table name starts with ``ma_`` too.

The store holds only per-key guidance level and playbook progress (BR-G-16). When it is down
miAssist keeps working: callers degrade by name (001's ``store/degrading.py``).
"""

from __future__ import annotations

from typing import Final

from sqlalchemy import MetaData, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

TABLE_PREFIX: Final = "ma_"

NAMING_CONVENTION: Final = {
    "ix": "ma_ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "ma_uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ma_ck_%(table_name)s_%(constraint_name)s",
    "fk": "ma_fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "ma_pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Every miAssist model's base; table names must start with ``ma_``."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class Database:
    """One engine and its session factory. Created lazily: no connection at construction."""

    def __init__(self, url: str, *, connect_timeout_s: float = 1.0) -> None:
        self.engine: AsyncEngine = create_async_engine(
            url,
            pool_pre_ping=True,
            pool_size=5,
            max_overflow=5,
            connect_args={"timeout": connect_timeout_s},
        )
        self.sessions: async_sessionmaker[AsyncSession] = async_sessionmaker(
            self.engine, expire_on_commit=False
        )

    async def ping(self) -> bool:
        """``SELECT 1``; True when the database answered. Never raises."""
        try:
            async with self.engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            return True
        except Exception:
            return False

    async def dispose(self) -> None:
        await self.engine.dispose()
