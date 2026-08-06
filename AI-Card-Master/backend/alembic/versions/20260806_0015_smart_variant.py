"""Smart Variant Sync: sync jobs and per-color variant items.

Revision ID: 20260806_0015
Revises: 20260806_0014
Create Date: 2026-08-06 23:30:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260806_0015"
down_revision: str | None = "20260806_0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create smart variant sync and item tables."""

    op.create_table(
        "smart_variant_syncs",
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
        sa.Column("product_category", sa.String(length=128), nullable=True),
        sa.Column(
            "engine_mode",
            sa.String(length=32),
            server_default=sa.text("'standard'"),
            nullable=False,
        ),
        sa.Column(
            "post_processing_mode",
            sa.String(length=32),
            server_default=sa.text("'fast'"),
            nullable=False,
        ),
        sa.Column(
            "apply_text_overlays",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column("source_image_object_key", sa.String(length=1024), nullable=False),
        sa.Column(
            "source_mime_type",
            sa.String(length=64),
            server_default=sa.text("'image/jpeg'"),
            nullable=False,
        ),
        sa.Column(
            "total_items",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "completed_items",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "failed_items",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "skipped_items",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "notify_telegram",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
        sa.Column(
            "notify_push",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
        sa.Column("telegram_notified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("push_notified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_smart_variant_syncs_user_id",
        "smart_variant_syncs",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        "ix_smart_variant_syncs_status",
        "smart_variant_syncs",
        ["status"],
        unique=False,
    )
    op.create_index(
        "ix_smart_variant_syncs_created_at",
        "smart_variant_syncs",
        ["created_at"],
        unique=False,
    )
    op.create_index(
        "ix_smart_variant_syncs_user_status",
        "smart_variant_syncs",
        ["user_id", "status"],
        unique=False,
    )
    op.create_index(
        "uq_smart_variant_syncs_user_idempotency",
        "smart_variant_syncs",
        ["user_id", "idempotency_key"],
        unique=True,
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )

    op.create_table(
        "smart_variant_items",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("sync_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("color_name", sa.String(length=64), nullable=False),
        sa.Column("color_hex", sa.String(length=7), nullable=True),
        sa.Column("color_slug", sa.String(length=96), nullable=False),
        sa.Column(
            "status",
            sa.String(length=32),
            server_default=sa.text("'pending'"),
            nullable=False,
        ),
        sa.Column("recolored_object_key", sa.String(length=1024), nullable=True),
        sa.Column("generation_job_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["sync_id"],
            ["smart_variant_syncs.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["generation_job_id"],
            ["generation_jobs.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_smart_variant_items_sync_id",
        "smart_variant_items",
        ["sync_id"],
        unique=False,
    )
    op.create_index(
        "ix_smart_variant_items_status",
        "smart_variant_items",
        ["status"],
        unique=False,
    )
    op.create_index(
        "ix_smart_variant_items_generation_job_id",
        "smart_variant_items",
        ["generation_job_id"],
        unique=False,
    )
    op.create_index(
        "ix_smart_variant_items_sync_status",
        "smart_variant_items",
        ["sync_id", "status"],
        unique=False,
    )
    op.create_index(
        "uq_smart_variant_items_sync_position",
        "smart_variant_items",
        ["sync_id", "position"],
        unique=True,
    )


def downgrade() -> None:
    """Drop smart variant tables."""

    op.drop_index(
        "uq_smart_variant_items_sync_position",
        table_name="smart_variant_items",
    )
    op.drop_index(
        "ix_smart_variant_items_sync_status",
        table_name="smart_variant_items",
    )
    op.drop_index(
        "ix_smart_variant_items_generation_job_id",
        table_name="smart_variant_items",
    )
    op.drop_index("ix_smart_variant_items_status", table_name="smart_variant_items")
    op.drop_index("ix_smart_variant_items_sync_id", table_name="smart_variant_items")
    op.drop_table("smart_variant_items")

    op.drop_index(
        "uq_smart_variant_syncs_user_idempotency",
        table_name="smart_variant_syncs",
    )
    op.drop_index(
        "ix_smart_variant_syncs_user_status",
        table_name="smart_variant_syncs",
    )
    op.drop_index(
        "ix_smart_variant_syncs_created_at",
        table_name="smart_variant_syncs",
    )
    op.drop_index("ix_smart_variant_syncs_status", table_name="smart_variant_syncs")
    op.drop_index("ix_smart_variant_syncs_user_id", table_name="smart_variant_syncs")
    op.drop_table("smart_variant_syncs")
