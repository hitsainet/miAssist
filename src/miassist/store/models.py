"""The store's two tables (001 FPRD §5.3; FTDD §4.1). Nothing else is stored (BR-G-16).

Every row is keyed by the SHA-256 of a person's key, never the key. ``state`` holds step ids,
approval ids and app resource ids only, never user text. Retention counts from ``updated_at``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from miassist.store.db import Base

LEVELS = ("beginner", "expert")


class Preference(Base):
    __tablename__ = "ma_preferences"
    __table_args__ = (CheckConstraint("guidance_level IN ('beginner', 'expert')", name="level"),)

    key_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    guidance_level: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class PlaybookProgress(Base):
    __tablename__ = "ma_playbook_progress"

    key_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    playbook_id: Mapped[str] = mapped_column(String(48), primary_key=True)
    subject: Mapped[str] = mapped_column(String(128), primary_key=True, server_default="")
    playbook_version: Mapped[int] = mapped_column(Integer, nullable=False)
    state: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
