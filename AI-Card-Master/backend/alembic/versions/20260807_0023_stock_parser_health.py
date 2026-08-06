"""Parser health table for isolated WB/Ozon stock-parser circuit breaker.

Revision ID: 20260807_0023
Revises: 20260806_0022
Create Date: 2026-08-07 01:20:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260807_0023"
down_revision: str | None = "20260806_0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create parser_health for broken/degraded marketplace adapter state."""

    op.create_table(
        "parser_health",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("marketplace", sa.String(length=32), nullable=False),
        sa.Column(
            "status",
            sa.String(length=32),
            server_default=sa.text("'healthy'"),
            nullable=False,
        ),
        sa.Column(
            "consecutive_errors",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("last_error_kind", sa.String(length=32), nullable=True),
        sa.Column("last_error_message", sa.Text(), nullable=True),
        sa.Column("last_traceback", sa.Text(), nullable=True),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_failure_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("broken_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("alert_sent_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_parser_health_marketplace",
        "parser_health",
        ["marketplace"],
        unique=True,
    )
    op.create_index("ix_parser_health_status", "parser_health", ["status"])


def downgrade() -> None:
    """Drop parser_health."""

    op.drop_index("ix_parser_health_status", table_name="parser_health")
    op.drop_index("uq_parser_health_marketplace", table_name="parser_health")
    op.drop_table("parser_health")
