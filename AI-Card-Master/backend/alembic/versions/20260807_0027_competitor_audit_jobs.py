"""Competitor audit jobs: manual WB/Ozon link deep scrape (plan §77).

Revision ID: 20260807_0027
Revises: 20260807_0026
Create Date: 2026-08-07 05:00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260807_0027"
down_revision: str | None = "20260807_0026"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create competitor_audit_jobs for async analyze-links scrape jobs."""

    op.create_table(
        "competitor_audit_jobs",
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
        sa.Column(
            "links_payload",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("result_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
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
        "ix_competitor_audit_jobs_user_id",
        "competitor_audit_jobs",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        "ix_competitor_audit_jobs_status",
        "competitor_audit_jobs",
        ["status"],
        unique=False,
    )
    op.create_index(
        "ix_competitor_audit_jobs_user_status",
        "competitor_audit_jobs",
        ["user_id", "status"],
        unique=False,
    )
    op.create_index(
        "uq_competitor_audit_jobs_user_idempotency",
        "competitor_audit_jobs",
        ["user_id", "idempotency_key"],
        unique=True,
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )


def downgrade() -> None:
    """Drop competitor_audit_jobs."""

    op.drop_index(
        "uq_competitor_audit_jobs_user_idempotency",
        table_name="competitor_audit_jobs",
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )
    op.drop_index(
        "ix_competitor_audit_jobs_user_status",
        table_name="competitor_audit_jobs",
    )
    op.drop_index("ix_competitor_audit_jobs_status", table_name="competitor_audit_jobs")
    op.drop_index("ix_competitor_audit_jobs_user_id", table_name="competitor_audit_jobs")
    op.drop_table("competitor_audit_jobs")
