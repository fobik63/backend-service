"""Hidden admin controls, bans, and provider cost monitoring.

Revision ID: 20260806_0006
Revises: 20260806_0005
Create Date: 2026-08-06 04:05:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260806_0006"
down_revision: str | None = "20260806_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add moderation fields and immutable API usage cost events."""

    op.add_column(
        "users",
        sa.Column(
            "is_banned",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
    )
    op.add_column("users", sa.Column("ban_reason", sa.Text(), nullable=True))
    op.add_column("users", sa.Column("banned_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "users",
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
    )
    op.create_index("ix_users_is_banned", "users", ["is_banned"], unique=False)
    op.create_index("ix_users_created_at", "users", ["created_at"], unique=False)

    op.create_table(
        "api_usage_costs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("generation_job_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("model_name", sa.String(length=128), nullable=True),
        sa.Column("operation", sa.String(length=128), nullable=False),
        sa.Column("units", sa.Integer(), server_default="1", nullable=False),
        sa.Column(
            "unit_cost_usd",
            sa.Numeric(precision=12, scale=6),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "total_cost_usd",
            sa.Numeric(precision=12, scale=6),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "currency",
            sa.String(length=3),
            server_default=sa.text("'USD'"),
            nullable=False,
        ),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["generation_job_id"],
            ["generation_jobs.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_api_usage_costs_user_id", "api_usage_costs", ["user_id"])
    op.create_index(
        "ix_api_usage_costs_generation_job_id",
        "api_usage_costs",
        ["generation_job_id"],
    )
    op.create_index("ix_api_usage_costs_provider", "api_usage_costs", ["provider"])
    op.create_index("ix_api_usage_costs_model_name", "api_usage_costs", ["model_name"])
    op.create_index("ix_api_usage_costs_operation", "api_usage_costs", ["operation"])
    op.create_index("ix_api_usage_costs_created_at", "api_usage_costs", ["created_at"])


def downgrade() -> None:
    """Remove admin moderation and cost monitoring storage."""

    op.drop_index("ix_api_usage_costs_created_at", table_name="api_usage_costs")
    op.drop_index("ix_api_usage_costs_operation", table_name="api_usage_costs")
    op.drop_index("ix_api_usage_costs_model_name", table_name="api_usage_costs")
    op.drop_index("ix_api_usage_costs_provider", table_name="api_usage_costs")
    op.drop_index("ix_api_usage_costs_generation_job_id", table_name="api_usage_costs")
    op.drop_index("ix_api_usage_costs_user_id", table_name="api_usage_costs")
    op.drop_table("api_usage_costs")

    op.drop_index("ix_users_created_at", table_name="users")
    op.drop_index("ix_users_is_banned", table_name="users")
    op.drop_column("users", "created_at")
    op.drop_column("users", "banned_at")
    op.drop_column("users", "ban_reason")
    op.drop_column("users", "is_banned")
