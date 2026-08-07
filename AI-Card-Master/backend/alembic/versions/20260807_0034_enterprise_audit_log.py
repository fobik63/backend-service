"""Enterprise Audit Log tables + indexes (plan §81).

Revision ID: 20260807_0034
Revises: 20260807_0033
Create Date: 2026-08-07 05:40:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260807_0034"
down_revision: str | None = "20260807_0033"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create hot audit_logs + cold audit_log_archives with search indexes."""

    op.create_table(
        "audit_logs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column(
            "status",
            sa.String(length=16),
            server_default=sa.text("'success'"),
            nullable=False,
        ),
        sa.Column("ip", sa.String(length=64), nullable=True),
        sa.Column("visitor_id", sa.String(length=128), nullable=True),
        sa.Column("telegram_id", sa.BigInteger(), nullable=True),
        sa.Column("user_agent", sa.String(length=512), nullable=True),
        sa.Column("endpoint", sa.String(length=512), nullable=True),
        sa.Column("http_method", sa.String(length=16), nullable=True),
        sa.Column("request_id", sa.String(length=64), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column(
            "actor_type",
            sa.String(length=32),
            server_default=sa.text("'user'"),
            nullable=False,
        ),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_audit_logs_user_id", "audit_logs", ["user_id"])
    op.create_index("ix_audit_logs_event_type", "audit_logs", ["event_type"])
    op.create_index("ix_audit_logs_status", "audit_logs", ["status"])
    op.create_index("ix_audit_logs_created_at", "audit_logs", ["created_at"])
    op.create_index("ix_audit_logs_request_id", "audit_logs", ["request_id"])
    op.create_index(
        "ix_audit_logs_user_id_created_at",
        "audit_logs",
        ["user_id", "created_at"],
    )
    op.create_index(
        "ix_audit_logs_event_type_created_at",
        "audit_logs",
        ["event_type", "created_at"],
    )
    op.create_index(
        "ix_audit_logs_ip_created_at",
        "audit_logs",
        ["ip", "created_at"],
    )

    op.create_table(
        "audit_log_archives",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("ip", sa.String(length=64), nullable=True),
        sa.Column("visitor_id", sa.String(length=128), nullable=True),
        sa.Column("telegram_id", sa.BigInteger(), nullable=True),
        sa.Column("user_agent", sa.String(length=512), nullable=True),
        sa.Column("endpoint", sa.String(length=512), nullable=True),
        sa.Column("http_method", sa.String(length=16), nullable=True),
        sa.Column("request_id", sa.String(length=64), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("actor_type", sa.String(length=32), nullable=False),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "archived_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_audit_log_archives_user_id_created_at",
        "audit_log_archives",
        ["user_id", "created_at"],
    )
    op.create_index(
        "ix_audit_log_archives_event_type_created_at",
        "audit_log_archives",
        ["event_type", "created_at"],
    )
    op.create_index(
        "ix_audit_log_archives_request_id",
        "audit_log_archives",
        ["request_id"],
    )
    op.create_index(
        "ix_audit_log_archives_created_at",
        "audit_log_archives",
        ["created_at"],
    )
    op.create_index(
        "ix_audit_log_archives_archived_at",
        "audit_log_archives",
        ["archived_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_audit_log_archives_archived_at", table_name="audit_log_archives")
    op.drop_index("ix_audit_log_archives_created_at", table_name="audit_log_archives")
    op.drop_index("ix_audit_log_archives_request_id", table_name="audit_log_archives")
    op.drop_index(
        "ix_audit_log_archives_event_type_created_at",
        table_name="audit_log_archives",
    )
    op.drop_index(
        "ix_audit_log_archives_user_id_created_at",
        table_name="audit_log_archives",
    )
    op.drop_table("audit_log_archives")

    op.drop_index("ix_audit_logs_ip_created_at", table_name="audit_logs")
    op.drop_index("ix_audit_logs_event_type_created_at", table_name="audit_logs")
    op.drop_index("ix_audit_logs_user_id_created_at", table_name="audit_logs")
    op.drop_index("ix_audit_logs_request_id", table_name="audit_logs")
    op.drop_index("ix_audit_logs_created_at", table_name="audit_logs")
    op.drop_index("ix_audit_logs_status", table_name="audit_logs")
    op.drop_index("ix_audit_logs_event_type", table_name="audit_logs")
    op.drop_index("ix_audit_logs_user_id", table_name="audit_logs")
    op.drop_table("audit_logs")
