"""Raw parser storage: sku_items + monthly-partitioned stock_snapshots.

Revision ID: 20260807_0024
Revises: 20260807_0023
Create Date: 2026-08-07 02:00:00
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260807_0024"
down_revision: str | None = "20260807_0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _month_start(year: int, month: int) -> datetime:
    return datetime(year, month, 1, tzinfo=UTC)


def _next_month(year: int, month: int) -> tuple[int, int]:
    if month == 12:
        return year + 1, 1
    return year, month + 1


def _partition_ddl(year: int, month: int) -> str:
    """CREATE TABLE … PARTITION OF for one calendar month (UTC)."""

    y2, m2 = _next_month(year, month)
    name = f"stock_snapshots_{year:04d}_{month:02d}"
    start = f"{year:04d}-{month:02d}-01 00:00:00+00"
    end = f"{y2:04d}-{m2:02d}-01 00:00:00+00"
    return f"""
    CREATE TABLE IF NOT EXISTS {name}
        PARTITION OF stock_snapshots
        FOR VALUES FROM ('{start}') TO ('{end}');
    """


def upgrade() -> None:
    """Create SKU dimension + RANGE-partitioned stock fact table."""

    op.create_table(
        "sku_items",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("marketplace", sa.String(length=32), nullable=False),
        sa.Column("article", sa.String(length=64), nullable=False),
        sa.Column("product_url", sa.String(length=1024), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=True),
        sa.Column(
            "is_active",
            sa.Boolean(),
            server_default=sa.text("true"),
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
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_sku_items_marketplace_article",
        "sku_items",
        ["marketplace", "article"],
        unique=True,
    )
    op.create_index("ix_sku_items_marketplace", "sku_items", ["marketplace"])
    op.create_index(
        "ix_sku_items_active",
        "sku_items",
        ["is_active"],
        postgresql_where=sa.text("is_active IS TRUE"),
    )

    # Parent partitioned table — PK must include RANGE key (captured_at).
    op.execute(
        """
        CREATE TABLE stock_snapshots (
            id UUID NOT NULL DEFAULT gen_random_uuid(),
            captured_at TIMESTAMPTZ NOT NULL,
            sku_id UUID NOT NULL,
            warehouse_id VARCHAR(64) NOT NULL,
            quantity INTEGER NOT NULL,
            price_kopecks BIGINT NOT NULL,
            currency VARCHAR(8) NOT NULL DEFAULT 'RUB',
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (id, captured_at),
            CONSTRAINT ck_stock_snapshots_quantity_nonneg
                CHECK (quantity >= 0),
            CONSTRAINT ck_stock_snapshots_price_nonneg
                CHECK (price_kopecks >= 0),
            CONSTRAINT fk_stock_snapshots_sku_id
                FOREIGN KEY (sku_id) REFERENCES sku_items (id) ON DELETE CASCADE
        ) PARTITION BY RANGE (captured_at);
        """
    )

    # Critical lookup path for sales math / history: (sku_id, timestamp).
    op.execute(
        """
        CREATE INDEX ix_stock_snapshots_sku_id_captured_at
            ON stock_snapshots (sku_id, captured_at DESC);
        """
    )
    op.execute(
        """
        CREATE INDEX ix_stock_snapshots_sku_warehouse_captured_at
            ON stock_snapshots (sku_id, warehouse_id, captured_at DESC);
        """
    )

    # Catch-all so inserts never fail before a month partition exists.
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS stock_snapshots_default
            PARTITION OF stock_snapshots DEFAULT;
        """
    )

    # Pre-create previous / current / next two months (UTC).
    now = datetime.now(UTC)
    year, month = now.year, now.month
    # Step back one month.
    if month == 1:
        year, month = year - 1, 12
    else:
        month -= 1
    for _ in range(4):
        op.execute(sa.text(_partition_ddl(year, month)))
        year, month = _next_month(year, month)

    # Auto-provision monthly partitions from workers / Beat.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION ensure_stock_snapshot_month_partition(
            p_ts TIMESTAMPTZ
        ) RETURNS TEXT
        LANGUAGE plpgsql
        AS $$
        DECLARE
            v_start TIMESTAMPTZ;
            v_end   TIMESTAMPTZ;
            v_name  TEXT;
        BEGIN
            v_start := date_trunc('month', p_ts AT TIME ZONE 'UTC')
                       AT TIME ZONE 'UTC';
            v_end   := (v_start + INTERVAL '1 month');
            v_name  := format(
                'stock_snapshots_%s',
                to_char(v_start, 'YYYY_MM')
            );

            EXECUTE format(
                'CREATE TABLE IF NOT EXISTS %I PARTITION OF stock_snapshots '
                'FOR VALUES FROM (%L) TO (%L)',
                v_name,
                v_start,
                v_end
            );
            RETURN v_name;
        END;
        $$;
        """
    )


def downgrade() -> None:
    """Drop partitioned stock fact table and SKU dimension."""

    op.execute("DROP FUNCTION IF EXISTS ensure_stock_snapshot_month_partition(TIMESTAMPTZ)")
    op.execute("DROP TABLE IF EXISTS stock_snapshots CASCADE")
    op.drop_index("ix_sku_items_active", table_name="sku_items")
    op.drop_index("ix_sku_items_marketplace", table_name="sku_items")
    op.drop_index("uq_sku_items_marketplace_article", table_name="sku_items")
    op.drop_table("sku_items")
