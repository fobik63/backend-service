"""Bulk Generation: batches, items, and in-app push notifications.

Revision ID: 20260806_0014
Revises: 20260806_0013
Create Date: 2026-08-06 23:10:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260806_0014"
down_revision: str | None = "20260806_0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create bulk generation tables and push notification inbox."""

    op.create_table(
        "bulk_generation_batches",
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
        sa.Column("source_zip_object_key", sa.String(length=1024), nullable=False),
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
        "ix_bulk_generation_batches_user_id",
        "bulk_generation_batches",
        ["user_id"],
    )
    op.create_index(
        "ix_bulk_generation_batches_status",
        "bulk_generation_batches",
        ["status"],
    )
    op.create_index(
        "ix_bulk_generation_batches_created_at",
        "bulk_generation_batches",
        ["created_at"],
    )
    op.create_index(
        "ix_bulk_generation_batches_user_status",
        "bulk_generation_batches",
        ["user_id", "status"],
    )
    op.create_index(
        "uq_bulk_generation_batches_user_idempotency",
        "bulk_generation_batches",
        ["user_id", "idempotency_key"],
        unique=True,
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )

    op.create_table(
        "bulk_generation_items",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("batch_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("product_key", sa.String(length=255), nullable=False),
        sa.Column("source_path", sa.String(length=1024), nullable=False),
        sa.Column(
            "status",
            sa.String(length=32),
            server_default=sa.text("'pending'"),
            nullable=False,
        ),
        sa.Column("input_object_key", sa.String(length=1024), nullable=True),
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
            ["batch_id"],
            ["bulk_generation_batches.id"],
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
        "ix_bulk_generation_items_batch_id",
        "bulk_generation_items",
        ["batch_id"],
    )
    op.create_index(
        "ix_bulk_generation_items_status",
        "bulk_generation_items",
        ["status"],
    )
    op.create_index(
        "ix_bulk_generation_items_generation_job_id",
        "bulk_generation_items",
        ["generation_job_id"],
    )
    op.create_index(
        "ix_bulk_generation_items_batch_status",
        "bulk_generation_items",
        ["batch_id", "status"],
    )
    op.create_index(
        "uq_bulk_generation_items_batch_position",
        "bulk_generation_items",
        ["batch_id", "position"],
        unique=True,
    )

    op.create_table(
        "user_push_notifications",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column(
            "data_json",
            sa.Text(),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_user_push_notifications_user_id",
        "user_push_notifications",
        ["user_id"],
    )
    op.create_index(
        "ix_user_push_notifications_created_at",
        "user_push_notifications",
        ["created_at"],
    )
    op.create_index(
        "ix_user_push_notifications_user_created",
        "user_push_notifications",
        ["user_id", "created_at"],
    )


def downgrade() -> None:
    """Drop bulk generation and push notification tables."""

    op.drop_index(
        "ix_user_push_notifications_user_created",
        table_name="user_push_notifications",
    )
    op.drop_index(
        "ix_user_push_notifications_created_at",
        table_name="user_push_notifications",
    )
    op.drop_index(
        "ix_user_push_notifications_user_id",
        table_name="user_push_notifications",
    )
    op.drop_table("user_push_notifications")

    op.drop_index(
        "uq_bulk_generation_items_batch_position",
        table_name="bulk_generation_items",
    )
    op.drop_index(
        "ix_bulk_generation_items_batch_status",
        table_name="bulk_generation_items",
    )
    op.drop_index(
        "ix_bulk_generation_items_generation_job_id",
        table_name="bulk_generation_items",
    )
    op.drop_index(
        "ix_bulk_generation_items_status",
        table_name="bulk_generation_items",
    )
    op.drop_index(
        "ix_bulk_generation_items_batch_id",
        table_name="bulk_generation_items",
    )
    op.drop_table("bulk_generation_items")

    op.drop_index(
        "uq_bulk_generation_batches_user_idempotency",
        table_name="bulk_generation_batches",
    )
    op.drop_index(
        "ix_bulk_generation_batches_user_status",
        table_name="bulk_generation_batches",
    )
    op.drop_index(
        "ix_bulk_generation_batches_created_at",
        table_name="bulk_generation_batches",
    )
    op.drop_index(
        "ix_bulk_generation_batches_status",
        table_name="bulk_generation_batches",
    )
    op.drop_index(
        "ix_bulk_generation_batches_user_id",
        table_name="bulk_generation_batches",
    )
    op.drop_table("bulk_generation_batches")
