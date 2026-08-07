"""AI Cost Dashboard: enrich usage events + daily rollups (plan §80).

Revision ID: 20260807_0033
Revises: 20260807_0032
Create Date: 2026-08-07 05:20:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260807_0033"
down_revision: str | None = "20260807_0032"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add per-call analytics columns and provider daily rollup table."""

    op.add_column(
        "api_usage_costs",
        sa.Column(
            "input_tokens",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
    )
    op.add_column(
        "api_usage_costs",
        sa.Column(
            "output_tokens",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
    )
    op.add_column(
        "api_usage_costs",
        sa.Column(
            "status",
            sa.String(length=16),
            server_default=sa.text("'Success'"),
            nullable=False,
        ),
    )
    op.add_column(
        "api_usage_costs",
        sa.Column("duration_ms", sa.Integer(), nullable=True),
    )
    op.add_column(
        "api_usage_costs",
        sa.Column("task_id", postgresql.UUID(as_uuid=True), nullable=True),
    )

    op.create_index("ix_api_usage_costs_status", "api_usage_costs", ["status"])
    op.create_index("ix_api_usage_costs_task_id", "api_usage_costs", ["task_id"])
    op.create_index(
        "ix_api_usage_costs_created_at_provider",
        "api_usage_costs",
        ["created_at", "provider"],
    )
    op.create_index(
        "ix_api_usage_costs_total_cost_created",
        "api_usage_costs",
        ["total_cost_usd", "created_at"],
    )

    # Backfill token columns from JSON metadata when present.
    op.execute(
        sa.text(
            """
            UPDATE api_usage_costs
            SET
                input_tokens = COALESCE(
                    NULLIF((metadata->>'input_tokens')::int, 0),
                    input_tokens
                ),
                output_tokens = COALESCE(
                    NULLIF((metadata->>'output_tokens')::int, 0),
                    output_tokens
                )
            WHERE metadata IS NOT NULL
              AND (
                metadata ? 'input_tokens'
                OR metadata ? 'output_tokens'
              )
            """
        )
    )

    op.create_table(
        "api_cost_daily_rollups",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("operation", sa.String(length=128), nullable=False),
        sa.Column(
            "events_count",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "success_count",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "error_count",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "timeout_count",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "generation_events_count",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "generation_cost_usd",
            sa.Numeric(precision=14, scale=6),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "total_cost_usd",
            sa.Numeric(precision=14, scale=6),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "total_input_tokens",
            sa.BigInteger(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "total_output_tokens",
            sa.BigInteger(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "total_duration_ms",
            sa.BigInteger(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "duration_samples",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "day",
            "provider",
            "operation",
            name="uq_api_cost_daily_rollups_day_provider_operation",
        ),
    )
    op.create_index(
        "ix_api_cost_daily_rollups_day",
        "api_cost_daily_rollups",
        ["day"],
    )
    op.create_index(
        "ix_api_cost_daily_rollups_provider_day",
        "api_cost_daily_rollups",
        ["provider", "day"],
    )


def downgrade() -> None:
    """Remove cost analytics rollups and enriched event columns."""

    op.drop_index(
        "ix_api_cost_daily_rollups_provider_day",
        table_name="api_cost_daily_rollups",
    )
    op.drop_index("ix_api_cost_daily_rollups_day", table_name="api_cost_daily_rollups")
    op.drop_table("api_cost_daily_rollups")

    op.drop_index("ix_api_usage_costs_total_cost_created", table_name="api_usage_costs")
    op.drop_index("ix_api_usage_costs_created_at_provider", table_name="api_usage_costs")
    op.drop_index("ix_api_usage_costs_task_id", table_name="api_usage_costs")
    op.drop_index("ix_api_usage_costs_status", table_name="api_usage_costs")
    op.drop_column("api_usage_costs", "task_id")
    op.drop_column("api_usage_costs", "duration_ms")
    op.drop_column("api_usage_costs", "status")
    op.drop_column("api_usage_costs", "output_tokens")
    op.drop_column("api_usage_costs", "input_tokens")
