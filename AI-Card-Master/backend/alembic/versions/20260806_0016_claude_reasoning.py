"""Claude 4.7 Vision & Reasoning async jobs.

Revision ID: 20260806_0016
Revises: 20260806_0015
Create Date: 2026-08-06 23:50:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260806_0016"
down_revision: str | None = "20260806_0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create durable Claude Vision / CoT job table."""

    op.create_table(
        "claude_reasoning_jobs",
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
        sa.Column(
            "image_object_keys",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "text_context",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("vision_result", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "reasoning_result",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("final_result", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
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
        "ix_claude_reasoning_jobs_user_id",
        "claude_reasoning_jobs",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        "ix_claude_reasoning_jobs_status",
        "claude_reasoning_jobs",
        ["status"],
        unique=False,
    )
    op.create_index(
        "ix_claude_reasoning_jobs_user_status",
        "claude_reasoning_jobs",
        ["user_id", "status"],
        unique=False,
    )
    op.create_index(
        "uq_claude_reasoning_jobs_user_idempotency",
        "claude_reasoning_jobs",
        ["user_id", "idempotency_key"],
        unique=True,
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )


def downgrade() -> None:
    """Drop Claude reasoning job table."""

    op.drop_index(
        "uq_claude_reasoning_jobs_user_idempotency",
        table_name="claude_reasoning_jobs",
    )
    op.drop_index(
        "ix_claude_reasoning_jobs_user_status",
        table_name="claude_reasoning_jobs",
    )
    op.drop_index("ix_claude_reasoning_jobs_status", table_name="claude_reasoning_jobs")
    op.drop_index("ix_claude_reasoning_jobs_user_id", table_name="claude_reasoning_jobs")
    op.drop_table("claude_reasoning_jobs")
