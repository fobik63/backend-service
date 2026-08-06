"""Claude 4.7 Strategic 'Killer' Recommendations Engine (AI Strategy) jobs.

Revision ID: 20260806_0019
Revises: 20260806_0018
Create Date: 2026-08-07 00:40:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260806_0019"
down_revision: str | None = "20260806_0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create durable AI Strategy job table."""

    op.create_table(
        "ai_strategy_jobs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=True),
        sa.Column(
            "status",
            sa.String(length=32),
            server_default=sa.text("'queued'"),
            nullable=False,
        ),
        sa.Column("celery_task_id", sa.String(length=255), nullable=True),
        sa.Column("model_name", sa.String(length=128), nullable=False),
        sa.Column("niche_key", sa.String(length=128), nullable=False),
        sa.Column("marketplace", sa.String(length=32), nullable=False),
        sa.Column(
            "user_card_payload",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "leader_card_payload",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "compare_config",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "compare_report",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "plan_result",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "input_tokens",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "output_tokens",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_ai_strategy_jobs_user_id",
        "ai_strategy_jobs",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        "ix_ai_strategy_jobs_status",
        "ai_strategy_jobs",
        ["status"],
        unique=False,
    )
    op.create_index(
        "ix_ai_strategy_jobs_user_status",
        "ai_strategy_jobs",
        ["user_id", "status"],
        unique=False,
    )
    op.create_index(
        "ix_ai_strategy_jobs_niche",
        "ai_strategy_jobs",
        ["niche_key"],
        unique=False,
    )
    op.create_index(
        "uq_ai_strategy_jobs_user_idempotency",
        "ai_strategy_jobs",
        ["user_id", "idempotency_key"],
        unique=True,
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )


def downgrade() -> None:
    """Drop AI Strategy job table."""

    op.drop_index(
        "uq_ai_strategy_jobs_user_idempotency",
        table_name="ai_strategy_jobs",
    )
    op.drop_index(
        "ix_ai_strategy_jobs_niche",
        table_name="ai_strategy_jobs",
    )
    op.drop_index(
        "ix_ai_strategy_jobs_user_status",
        table_name="ai_strategy_jobs",
    )
    op.drop_index(
        "ix_ai_strategy_jobs_status",
        table_name="ai_strategy_jobs",
    )
    op.drop_index(
        "ix_ai_strategy_jobs_user_id",
        table_name="ai_strategy_jobs",
    )
    op.drop_table("ai_strategy_jobs")
