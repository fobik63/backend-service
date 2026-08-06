"""Competitor negative-review pain analysis jobs.

Revision ID: 20260806_0021
Revises: 20260806_0020
Create Date: 2026-08-07 01:00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260806_0021"
down_revision: str | None = "20260806_0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create durable pain-analysis job table."""

    op.create_table(
        "pain_analysis_jobs",
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
        sa.Column("product_name", sa.String(length=300), nullable=False),
        sa.Column("platform", sa.String(length=32), nullable=False),
        sa.Column(
            "request_payload",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "filter_preview",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "analysis_result",
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
        "ix_pain_analysis_jobs_user_id",
        "pain_analysis_jobs",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        "ix_pain_analysis_jobs_status",
        "pain_analysis_jobs",
        ["status"],
        unique=False,
    )
    op.create_index(
        "ix_pain_analysis_jobs_user_status",
        "pain_analysis_jobs",
        ["user_id", "status"],
        unique=False,
    )
    op.create_index(
        "ix_pain_analysis_jobs_platform",
        "pain_analysis_jobs",
        ["platform"],
        unique=False,
    )
    op.create_index(
        "uq_pain_analysis_jobs_user_idempotency",
        "pain_analysis_jobs",
        ["user_id", "idempotency_key"],
        unique=True,
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )


def downgrade() -> None:
    """Drop pain-analysis job table."""

    op.drop_index(
        "uq_pain_analysis_jobs_user_idempotency",
        table_name="pain_analysis_jobs",
    )
    op.drop_index("ix_pain_analysis_jobs_platform", table_name="pain_analysis_jobs")
    op.drop_index(
        "ix_pain_analysis_jobs_user_status",
        table_name="pain_analysis_jobs",
    )
    op.drop_index("ix_pain_analysis_jobs_status", table_name="pain_analysis_jobs")
    op.drop_index("ix_pain_analysis_jobs_user_id", table_name="pain_analysis_jobs")
    op.drop_table("pain_analysis_jobs")
