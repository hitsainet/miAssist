"""Core's two tables (001 FTASKS 6.1; FPRD §5.3).

Revision ID: 0002_core_tables
Revises: 0001_base
Create Date: 2026-11-16
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0002_core_tables"
down_revision: str | None = "0001_base"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ma_preferences",
        sa.Column("key_hash", sa.String(64), nullable=False),
        sa.Column("guidance_level", sa.String(16), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint(
            "guidance_level IN ('beginner', 'expert')", name="ma_ck_ma_preferences_level"
        ),
        sa.PrimaryKeyConstraint("key_hash", name="ma_pk_ma_preferences"),
    )
    op.create_table(
        "ma_playbook_progress",
        sa.Column("key_hash", sa.String(64), nullable=False),
        sa.Column("playbook_id", sa.String(48), nullable=False),
        sa.Column("subject", sa.String(128), nullable=False, server_default=""),
        sa.Column("playbook_version", sa.Integer(), nullable=False),
        sa.Column("state", JSONB(), nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.PrimaryKeyConstraint(
            "key_hash", "playbook_id", "subject", name="ma_pk_ma_playbook_progress"
        ),
    )


def downgrade() -> None:
    op.drop_table("ma_playbook_progress")
    op.drop_table("ma_preferences")
