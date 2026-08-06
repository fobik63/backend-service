"""Claude analysis transactional outbox for Celery dispatch.

Revision ID: 20260806_0022
Revises: 20260806_0021
Create Date: 2026-08-07 01:10:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260806_0022"
down_revision: str | None = "20260806_0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create durable Claude analysis outbox table."""

    op.create_table(
        "claude_analysis_outbox",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "event_type",
            sa.String(length=64),
            server_default=sa.text("'run_chain_of_thought'"),
            nullable=False,
        ),
        sa.Column("aggregate_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("deduplication_key", sa.String(length=512), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "status",
            sa.String(length=32),
            server_default=sa.text("'pending'"),
            nullable=False,
        ),
        sa.Column(
            "attempts",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
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
        "ix_claude_analysis_outbox_event_type",
        "claude_analysis_outbox",
        ["event_type"],
        unique=False,
    )
    op.create_index(
        "ix_claude_analysis_outbox_aggregate_id",
        "claude_analysis_outbox",
        ["aggregate_id"],
        unique=False,
    )
    op.create_index(
        "ix_claude_analysis_outbox_status",
        "claude_analysis_outbox",
        ["status"],
        unique=False,
    )
    op.create_index(
        "ix_claude_analysis_outbox_available_at",
        "claude_analysis_outbox",
        ["available_at"],
        unique=False,
    )


def downgrade() -> None:
    """Drop Claude analysis outbox table."""

    op.drop_index(
        "ix_claude_analysis_outbox_available_at",
        table_name="claude_analysis_outbox",
    )
    op.drop_index("ix_claude_analysis_outbox_status", table_name="claude_analysis_outbox")
    op.drop_index(
        "ix_claude_analysis_outbox_aggregate_id",
        table_name="claude_analysis_outbox",
    )
    op.drop_index(
        "ix_claude_analysis_outbox_event_type",
        table_name="claude_analysis_outbox",
    )
    op.drop_table("claude_analysis_outbox")
