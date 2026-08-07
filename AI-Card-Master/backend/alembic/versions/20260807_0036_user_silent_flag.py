"""Alembic: users.is_flagged + users.flag_reason for silent banning.

Revision ID: 20260807_0036
Revises: 20260807_0035
Create Date: 2026-08-07 21:40:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260807_0036"
down_revision: str | None = "20260807_0035"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add silent-ban columns to users."""

    op.add_column(
        "users",
        sa.Column(
            "is_flagged",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
    )
    op.add_column(
        "users",
        sa.Column("flag_reason", sa.String(length=64), nullable=True),
    )
    op.create_index("ix_users_is_flagged", "users", ["is_flagged"])


def downgrade() -> None:
    """Drop silent-ban columns from users."""

    op.drop_index("ix_users_is_flagged", table_name="users")
    op.drop_column("users", "flag_reason")
    op.drop_column("users", "is_flagged")
