"""Eye-of-God jobs: parser sales spike → Claude Vision money-trigger JSON.

Revision ID: 20260807_0026
Revises: 20260807_0025
Create Date: 2026-08-07 04:00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260807_0026"
down_revision: str | None = "20260807_0025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create eye_of_god_jobs for money-confirmed trigger persistence."""

    op.create_table(
        "eye_of_god_jobs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("sku_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=True),
        sa.Column(
            "status",
            sa.String(length=32),
            server_default=sa.text("'queued'"),
            nullable=False,
        ),
        sa.Column("celery_task_id", sa.String(length=255), nullable=True),
        sa.Column("model_name", sa.String(length=128), nullable=False),
        sa.Column("marketplace", sa.String(length=32), nullable=False),
        sa.Column("article", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=True),
        sa.Column("product_url", sa.String(length=1024), nullable=True),
        sa.Column(
            "spike_payload",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "image_urls",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("vision_result", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "money_trigger_config",
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
        sa.ForeignKeyConstraint(["sku_id"], ["sku_items.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_eye_of_god_jobs_sku_id",
        "eye_of_god_jobs",
        ["sku_id"],
        unique=False,
    )
    op.create_index(
        "ix_eye_of_god_jobs_status",
        "eye_of_god_jobs",
        ["status"],
        unique=False,
    )
    op.create_index(
        "ix_eye_of_god_jobs_sku_created",
        "eye_of_god_jobs",
        ["sku_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "uq_eye_of_god_jobs_idempotency",
        "eye_of_god_jobs",
        ["idempotency_key"],
        unique=True,
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )


def downgrade() -> None:
    """Drop eye_of_god_jobs."""

    op.drop_index(
        "uq_eye_of_god_jobs_idempotency",
        table_name="eye_of_god_jobs",
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )
    op.drop_index("ix_eye_of_god_jobs_sku_created", table_name="eye_of_god_jobs")
    op.drop_index("ix_eye_of_god_jobs_status", table_name="eye_of_god_jobs")
    op.drop_index("ix_eye_of_god_jobs_sku_id", table_name="eye_of_god_jobs")
    op.drop_table("eye_of_god_jobs")
