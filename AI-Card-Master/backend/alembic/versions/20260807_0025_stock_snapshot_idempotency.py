"""Unique (sku, warehouse, captured_at) for idempotent parser retries.

Revision ID: 20260807_0025
Revises: 20260807_0024
Create Date: 2026-08-07 03:00:00
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260807_0025"
down_revision: str | None = "20260807_0024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Prevent duplicate nightly snapshots when a Celery worker restarts."""

    # Partition key (captured_at) must be part of UNIQUE on the parent table.
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_stock_snapshots_sku_warehouse_captured
            ON stock_snapshots (sku_id, warehouse_id, captured_at);
        """
    )


def downgrade() -> None:
    """Drop idempotency unique index."""

    op.execute(
        "DROP INDEX IF EXISTS uq_stock_snapshots_sku_warehouse_captured"
    )
