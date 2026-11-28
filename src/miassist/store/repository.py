"""The store's API (001 FR-7, FR-20; FTDD §4.2). Keys arrive already hashed (``key_hash``).

No read writes a row (A13). ``forget`` deletes both tables' rows for one key in one transaction.
``sweep`` deletes rows not updated for ``retention_days`` (idempotent; safe with several replicas).
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert

from miassist.store.db import Database
from miassist.store.models import LEVELS, PlaybookProgress, Preference


def hash_key(key: str) -> str:
    """The SHA-256 hex digest of a person's key: the only form ever stored."""
    return hashlib.sha256(key.encode("ascii")).hexdigest()


class SqlStore:
    def __init__(self, database: Database) -> None:
        self.db = database

    async def level(self, key_hash: str) -> str | None:
        async with self.db.sessions() as session:
            row = await session.get(Preference, key_hash)
            return row.guidance_level if row is not None else None

    async def set_level(self, key_hash: str, level: str) -> None:
        if level not in LEVELS:
            raise ValueError(f"unknown level {level!r}")
        statement = insert(Preference).values(key_hash=key_hash, guidance_level=level)
        statement = statement.on_conflict_do_update(
            index_elements=[Preference.key_hash],
            set_={"guidance_level": level, "updated_at": func.now()},
        )
        async with self.db.sessions() as session, session.begin():
            await session.execute(statement)

    async def progress(
        self, key_hash: str, playbook_id: str, subject: str = ""
    ) -> dict[str, Any] | None:
        async with self.db.sessions() as session:
            row = await session.get(PlaybookProgress, (key_hash, playbook_id, subject))
            if row is None:
                return None
            return {"playbook_version": row.playbook_version, "state": row.state}

    async def save_progress(
        self, key_hash: str, playbook_id: str, subject: str, version: int, state: dict[str, Any]
    ) -> None:
        statement = insert(PlaybookProgress).values(
            key_hash=key_hash,
            playbook_id=playbook_id,
            subject=subject,
            playbook_version=version,
            state=state,
        )
        statement = statement.on_conflict_do_update(
            index_elements=[
                PlaybookProgress.key_hash,
                PlaybookProgress.playbook_id,
                PlaybookProgress.subject,
            ],
            set_={"playbook_version": version, "state": state, "updated_at": func.now()},
        )
        async with self.db.sessions() as session, session.begin():
            await session.execute(statement)

    async def forget(self, key_hash: str) -> None:
        async with self.db.sessions() as session, session.begin():
            await session.execute(
                delete(PlaybookProgress).where(PlaybookProgress.key_hash == key_hash)
            )
            await session.execute(delete(Preference).where(Preference.key_hash == key_hash))

    async def sweep(self, now: datetime, retention_days: int) -> int:
        cutoff = now - timedelta(days=retention_days)
        async with self.db.sessions() as session, session.begin():
            first = await session.execute(
                delete(PlaybookProgress).where(PlaybookProgress.updated_at < cutoff)
            )
            second = await session.execute(delete(Preference).where(Preference.updated_at < cutoff))
        return int(first.rowcount or 0) + int(second.rowcount or 0)  # type: ignore[attr-defined]

    async def has_any(self, key_hash: str) -> bool:
        async with self.db.sessions() as session:
            found = await session.execute(
                select(Preference.key_hash).where(Preference.key_hash == key_hash)
            )
            return found.first() is not None
