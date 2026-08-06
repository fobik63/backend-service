"""Churn Prevention / Win-back: last_seen, telegram_id, offers, style notify log.

Revision ID: 20260806_0013
Revises: 20260806_0012
Create Date: 2026-08-06 22:30:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260806_0013"
down_revision: str | None = "20260806_0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add activity/Telegram fields and win-back offer tables."""

    op.add_column(
        "users",
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column("telegram_id", sa.BigInteger(), nullable=True),
    )
    op.create_index("ix_users_last_seen_at", "users", ["last_seen_at"], unique=False)
    op.create_index("ix_users_telegram_id", "users", ["telegram_id"], unique=True)

    op.create_table(
        "winback_offers",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("trigger", sa.String(length=32), nullable=False),
        sa.Column("offer_type", sa.String(length=32), nullable=False),
        sa.Column(
            "status",
            sa.String(length=32),
            server_default=sa.text("'pending'"),
            nullable=False,
        ),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("free_generations", sa.Integer(), nullable=True),
        sa.Column("discount_percent", sa.Integer(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_winback_offers_user_id", "winback_offers", ["user_id"])
    op.create_index("ix_winback_offers_trigger", "winback_offers", ["trigger"])
    op.create_index("ix_winback_offers_offer_type", "winback_offers", ["offer_type"])
    op.create_index("ix_winback_offers_status", "winback_offers", ["status"])
    op.create_index("ix_winback_offers_expires_at", "winback_offers", ["expires_at"])
    op.create_index("ix_winback_offers_created_at", "winback_offers", ["created_at"])
    op.create_index(
        "ix_winback_offers_user_status",
        "winback_offers",
        ["user_id", "status"],
    )

    op.create_table(
        "winback_style_notifications",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("style_key", sa.String(length=64), nullable=False),
        sa.Column("campaign_key", sa.String(length=64), nullable=False),
        sa.Column(
            "sent_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_winback_style_notifications_user_id",
        "winback_style_notifications",
        ["user_id"],
    )
    op.create_index(
        "uq_winback_style_notifications_user_campaign",
        "winback_style_notifications",
        ["user_id", "style_key", "campaign_key"],
        unique=True,
    )


def downgrade() -> None:
    """Drop win-back tables and user activity/Telegram columns."""

    op.drop_index(
        "uq_winback_style_notifications_user_campaign",
        table_name="winback_style_notifications",
    )
    op.drop_index(
        "ix_winback_style_notifications_user_id",
        table_name="winback_style_notifications",
    )
    op.drop_table("winback_style_notifications")

    op.drop_index("ix_winback_offers_user_status", table_name="winback_offers")
    op.drop_index("ix_winback_offers_created_at", table_name="winback_offers")
    op.drop_index("ix_winback_offers_expires_at", table_name="winback_offers")
    op.drop_index("ix_winback_offers_status", table_name="winback_offers")
    op.drop_index("ix_winback_offers_offer_type", table_name="winback_offers")
    op.drop_index("ix_winback_offers_trigger", table_name="winback_offers")
    op.drop_index("ix_winback_offers_user_id", table_name="winback_offers")
    op.drop_table("winback_offers")

    op.drop_index("ix_users_telegram_id", table_name="users")
    op.drop_index("ix_users_last_seen_at", table_name="users")
    op.drop_column("users", "telegram_id")
    op.drop_column("users", "last_seen_at")
