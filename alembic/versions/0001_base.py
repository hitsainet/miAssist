"""The empty base revision (Foundation task 5.2). Feature 001 adds the tables (its 0002).

Revision ID: 0001_base
Revises:
Create Date: 2026-11-16
"""

from __future__ import annotations

from collections.abc import Sequence

revision: str = "0001_base"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
