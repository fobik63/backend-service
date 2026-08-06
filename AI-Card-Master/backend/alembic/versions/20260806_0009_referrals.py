"""Referral codes and paid-friend bonus state.

Revision ID: 20260806_0009
Revises: 20260806_0008
Create Date: 2026-08-06 22:30:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260806_0009"
down_revision: str | None = "20260806_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add referral ownership, invite links, and one-time bonus marker."""

    op.add_column("users", sa.Column("referral_code", sa.String(length=16), nullable=True))
    op.add_column(
        "users",
        sa.Column("referred_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column("referral_bonus_granted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_unique_constraint("uq_users_referral_code", "users", ["referral_code"])
    op.create_foreign_key(
        "fk_users_referred_by_user_id_users",
        "users",
        "users",
        ["referred_by_user_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_users_referral_code", "users", ["referral_code"], unique=False)
    op.create_index(
        "ix_users_referred_by_user_id",
        "users",
        ["referred_by_user_id"],
        unique=False,
    )


def downgrade() -> None:
    """Remove referral tracking columns."""

    op.drop_index("ix_users_referred_by_user_id", table_name="users")
    op.drop_index("ix_users_referral_code", table_name="users")
    op.drop_constraint("fk_users_referred_by_user_id_users", "users", type_="foreignkey")
    op.drop_constraint("uq_users_referral_code", "users", type_="unique")
    op.drop_column("users", "referral_bonus_granted_at")
    op.drop_column("users", "referred_by_user_id")
    op.drop_column("users", "referral_code")
