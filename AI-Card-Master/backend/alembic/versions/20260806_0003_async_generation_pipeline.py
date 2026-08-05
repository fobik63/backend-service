"""Durable generation jobs, provider attempts, webhooks, and outbox.

Revision ID: 20260806_0003
Revises: 20260806_0002
Create Date: 2026-08-06 01:55:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260806_0003"
down_revision: str | None = "20260806_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the DB-backed asynchronous generation state machine."""

    op.create_table(
        "generation_jobs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=True),
        sa.Column(
            "status", sa.String(length=32), server_default="queued", nullable=False
        ),
        sa.Column("progress", sa.Integer(), server_default="0", nullable=False),
        sa.Column("product_category", sa.String(length=128), nullable=True),
        sa.Column("subscription_status", sa.String(length=32), nullable=False),
        sa.Column("input_object_key", sa.String(length=1024), nullable=False),
        sa.Column("archive_object_key", sa.String(length=1024), nullable=True),
        sa.Column(
            "apply_text_overlays",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
        sa.Column(
            "overlay_texts", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
        sa.Column("provider_used", sa.String(length=64), nullable=True),
        sa.Column("warning", sa.String(length=500), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "error_retryable", sa.Boolean(), server_default=sa.false(), nullable=False
        ),
        sa.Column(
            "coin_charged", sa.Boolean(), server_default=sa.false(), nullable=False
        ),
        sa.Column(
            "coin_refunded", sa.Boolean(), server_default=sa.false(), nullable=False
        ),
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
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deadline_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "progress >= 0 AND progress <= 100",
            name="ck_generation_jobs_progress",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "idempotency_key",
            name="uq_generation_jobs_user_idempotency",
        ),
    )
    op.create_index("ix_generation_jobs_user_id", "generation_jobs", ["user_id"])
    op.create_index("ix_generation_jobs_status", "generation_jobs", ["status"])
    op.create_index("ix_generation_jobs_created_at", "generation_jobs", ["created_at"])
    op.create_index(
        "ix_generation_jobs_deadline_at", "generation_jobs", ["deadline_at"]
    )

    op.create_table(
        "generation_slides",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("slide_key", sa.String(length=64), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column(
            "status", sa.String(length=32), server_default="queued", nullable=False
        ),
        sa.Column("progress", sa.Integer(), server_default="0", nullable=False),
        sa.Column("selected_style", sa.String(length=500), nullable=False),
        sa.Column("prompt_used", sa.Text(), nullable=False),
        sa.Column("provider_used", sa.String(length=64), nullable=True),
        sa.Column("result_object_key", sa.String(length=1024), nullable=True),
        sa.Column("result_mime_type", sa.String(length=128), nullable=True),
        sa.Column("warning", sa.String(length=500), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "error_retryable", sa.Boolean(), server_default=sa.false(), nullable=False
        ),
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
        sa.CheckConstraint(
            "progress >= 0 AND progress <= 100",
            name="ck_generation_slides_progress",
        ),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["generation_jobs.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "job_id",
            "slide_key",
            name="uq_generation_slides_job_key",
        ),
        sa.UniqueConstraint(
            "job_id",
            "position",
            name="uq_generation_slides_job_position",
        ),
    )
    op.create_index("ix_generation_slides_job_id", "generation_slides", ["job_id"])
    op.create_index("ix_generation_slides_status", "generation_slides", ["status"])

    op.create_table(
        "generation_provider_attempts",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("slide_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider_name", sa.String(length=64), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("external_job_id", sa.String(length=512), nullable=True),
        sa.Column("reply_ref", sa.String(length=1024), nullable=False),
        sa.Column(
            "status", sa.String(length=64), server_default="created", nullable=False
        ),
        sa.Column("progress", sa.Integer(), server_default="0", nullable=False),
        sa.Column("result_url", sa.String(length=2048), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("abandoned", sa.Boolean(), server_default=sa.false(), nullable=False),
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
        sa.ForeignKeyConstraint(
            ["slide_id"],
            ["generation_slides.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "slide_id",
            "attempt_number",
            name="uq_generation_provider_attempt_slide_number",
        ),
        sa.UniqueConstraint(
            "reply_ref",
            name="uq_generation_provider_attempt_reply_ref",
        ),
        sa.UniqueConstraint(
            "provider_name",
            "external_job_id",
            name="uq_generation_provider_attempt_external",
        ),
    )
    op.create_index(
        "ix_generation_provider_attempts_slide_id",
        "generation_provider_attempts",
        ["slide_id"],
    )
    op.create_index(
        "ix_generation_provider_attempts_provider_name",
        "generation_provider_attempts",
        ["provider_name"],
    )
    op.create_index(
        "ix_generation_provider_attempts_external_job_id",
        "generation_provider_attempts",
        ["external_job_id"],
    )

    op.create_table(
        "generation_webhook_events",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("provider_name", sa.String(length=64), nullable=False),
        sa.Column("event_id", sa.String(length=512), nullable=False),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "raw_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.Column("processed", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column(
            "received_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "provider_name",
            "event_id",
            name="uq_generation_webhook_provider_event",
        ),
    )
    op.create_index(
        "ix_generation_webhook_events_provider_name",
        "generation_webhook_events",
        ["provider_name"],
    )
    op.create_index(
        "ix_generation_webhook_events_payload_hash",
        "generation_webhook_events",
        ["payload_hash"],
    )
    op.create_index(
        "ix_generation_webhook_events_processed",
        "generation_webhook_events",
        ["processed"],
    )

    op.create_table(
        "generation_outbox",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("aggregate_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("deduplication_key", sa.String(length=512), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "status", sa.String(length=32), server_default="pending", nullable=False
        ),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "available_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("deduplication_key"),
    )
    op.create_index(
        "ix_generation_outbox_event_type", "generation_outbox", ["event_type"]
    )
    op.create_index(
        "ix_generation_outbox_aggregate_id", "generation_outbox", ["aggregate_id"]
    )
    op.create_index("ix_generation_outbox_status", "generation_outbox", ["status"])
    op.create_index(
        "ix_generation_outbox_available_at", "generation_outbox", ["available_at"]
    )


def downgrade() -> None:
    """Remove asynchronous generation workflow tables."""

    op.drop_index("ix_generation_outbox_available_at", table_name="generation_outbox")
    op.drop_index("ix_generation_outbox_status", table_name="generation_outbox")
    op.drop_index("ix_generation_outbox_aggregate_id", table_name="generation_outbox")
    op.drop_index("ix_generation_outbox_event_type", table_name="generation_outbox")
    op.drop_table("generation_outbox")

    op.drop_index(
        "ix_generation_webhook_events_processed",
        table_name="generation_webhook_events",
    )
    op.drop_index(
        "ix_generation_webhook_events_payload_hash",
        table_name="generation_webhook_events",
    )
    op.drop_index(
        "ix_generation_webhook_events_provider_name",
        table_name="generation_webhook_events",
    )
    op.drop_table("generation_webhook_events")

    op.drop_index(
        "ix_generation_provider_attempts_external_job_id",
        table_name="generation_provider_attempts",
    )
    op.drop_index(
        "ix_generation_provider_attempts_provider_name",
        table_name="generation_provider_attempts",
    )
    op.drop_index(
        "ix_generation_provider_attempts_slide_id",
        table_name="generation_provider_attempts",
    )
    op.drop_table("generation_provider_attempts")

    op.drop_index("ix_generation_slides_status", table_name="generation_slides")
    op.drop_index("ix_generation_slides_job_id", table_name="generation_slides")
    op.drop_table("generation_slides")

    op.drop_index("ix_generation_jobs_deadline_at", table_name="generation_jobs")
    op.drop_index("ix_generation_jobs_created_at", table_name="generation_jobs")
    op.drop_index("ix_generation_jobs_status", table_name="generation_jobs")
    op.drop_index("ix_generation_jobs_user_id", table_name="generation_jobs")
    op.drop_table("generation_jobs")
