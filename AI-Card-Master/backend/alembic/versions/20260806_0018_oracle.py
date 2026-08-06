"""Claude 4.7 Market Gap & Trend Prediction (The Oracle) jobs.

Revision ID: 20260806_0018
Revises: 20260806_0017
Create Date: 2026-08-07 00:05:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260806_0018"
down_revision: str | None = "20260806_0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create durable Oracle prediction job table."""

    op.create_table(
        "oracle_prediction_jobs",
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
            "queries_payload",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "supply_payload",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "gap_config",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("scan_report", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "prediction_result",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "notifications",
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
        "ix_oracle_prediction_jobs_user_id",
        "oracle_prediction_jobs",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        "ix_oracle_prediction_jobs_status",
        "oracle_prediction_jobs",
        ["status"],
        unique=False,
    )
    op.create_index(
        "ix_oracle_prediction_jobs_user_status",
        "oracle_prediction_jobs",
        ["user_id", "status"],
        unique=False,
    )
    op.create_index(
        "ix_oracle_prediction_jobs_niche",
        "oracle_prediction_jobs",
        ["niche_key"],
        unique=False,
    )
    op.create_index(
        "uq_oracle_prediction_jobs_user_idempotency",
        "oracle_prediction_jobs",
        ["user_id", "idempotency_key"],
        unique=True,
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )


def downgrade() -> None:
    """Drop Oracle prediction job table."""

    op.drop_index(
        "uq_oracle_prediction_jobs_user_idempotency",
        table_name="oracle_prediction_jobs",
    )
    op.drop_index(
        "ix_oracle_prediction_jobs_niche",
        table_name="oracle_prediction_jobs",
    )
    op.drop_index(
        "ix_oracle_prediction_jobs_user_status",
        table_name="oracle_prediction_jobs",
    )
    op.drop_index(
        "ix_oracle_prediction_jobs_status",
        table_name="oracle_prediction_jobs",
    )
    op.drop_index(
        "ix_oracle_prediction_jobs_user_id",
        table_name="oracle_prediction_jobs",
    )
    op.drop_table("oracle_prediction_jobs")
