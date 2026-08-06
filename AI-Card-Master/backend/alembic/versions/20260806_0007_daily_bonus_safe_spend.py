"""Daily retention bonus and Safe Spend balance invariant.

Revision ID: 20260806_0007
Revises: 20260806_0006
Create Date: 2026-08-06 21:30:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260806_0007"
down_revision: str | None = "20260806_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Track daily free bonus claims and enforce non-negative credit balances."""

    op.add_column(
        "users",
        sa.Column("daily_bonus_claimed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column(
            "daily_bonus_streak",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
    )
    op.create_check_constraint(
        "ck_users_ai_coins_non_negative",
        "users",
        "ai_coins >= 0",
    )
    op.create_check_constraint(
        "ck_users_daily_bonus_streak_non_negative",
        "users",
        "daily_bonus_streak >= 0",
    )


def downgrade() -> None:
    """Remove daily bonus state and Safe Spend constraints."""

    op.drop_constraint(
        "ck_users_daily_bonus_streak_non_negative",
        "users",
        type_="check",
    )
    op.drop_constraint("ck_users_ai_coins_non_negative", "users", type_="check")
    op.drop_column("users", "daily_bonus_streak")
    op.drop_column("users", "daily_bonus_claimed_at")
