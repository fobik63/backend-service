"""ORM models for marketplace stock-parser health + raw SKU / snapshot storage.

``stock_snapshots`` is RANGE-partitioned by month on ``captured_at`` so hot
queries stay on current partitions while historical months can be detached.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class ParserHealth(Base):
    """One row per marketplace: healthy / degraded / broken / disabled."""

    __tablename__ = "parser_health"
    __table_args__ = (
        Index("uq_parser_health_marketplace", "marketplace", unique=True),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
        server_default=text("gen_random_uuid()"),
    )
    marketplace: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="healthy",
        server_default=text("'healthy'"),
        index=True,
    )
    consecutive_errors: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
    )
    last_error_kind: Mapped[str | None] = mapped_column(String(32), nullable=True)
    last_error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_traceback: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_success_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    last_failure_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    broken_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    alert_sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("NOW()"),
        index=True,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("NOW()"),
    )


class SkuItem(Base):
    """Tracked SKU (артикул + URL + marketplace). Small dimension table."""

    __tablename__ = "sku_items"
    __table_args__ = (
        Index(
            "uq_sku_items_marketplace_article",
            "marketplace",
            "article",
            unique=True,
        ),
        Index("ix_sku_items_marketplace", "marketplace"),
        Index(
            "ix_sku_items_active",
            "is_active",
            postgresql_where=text("is_active IS TRUE"),
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
        server_default=text("gen_random_uuid()"),
    )
    marketplace: Mapped[str] = mapped_column(String(32), nullable=False)
    article: Mapped[str] = mapped_column(String(64), nullable=False)
    product_url: Mapped[str] = mapped_column(String(1024), nullable=False)
    title: Mapped[str | None] = mapped_column(String(500), nullable=True)
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default=text("true"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("NOW()"),
        index=True,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("NOW()"),
    )


class StockSnapshot(Base):
    """Raw warehouse stock + price observation (monthly RANGE partitions).

    PostgreSQL requires the partition key in the primary key, so PK is
    ``(id, captured_at)``. Hot path index: ``(sku_id, captured_at)``.
    """

    __tablename__ = "stock_snapshots"
    __table_args__ = (
        Index(
            "ix_stock_snapshots_sku_id_captured_at",
            "sku_id",
            "captured_at",
        ),
        Index(
            "ix_stock_snapshots_sku_warehouse_captured_at",
            "sku_id",
            "warehouse_id",
            "captured_at",
        ),
        # Includes partition key so PostgreSQL accepts UNIQUE on the parent.
        # Worker restarts upsert the same (sku, warehouse, captured_at) row.
        Index(
            "uq_stock_snapshots_sku_warehouse_captured",
            "sku_id",
            "warehouse_id",
            "captured_at",
            unique=True,
        ),
        {
            "postgresql_partition_by": "RANGE (captured_at)",
        },
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
        server_default=text("gen_random_uuid()"),
    )
    # Partition key must be part of PK for declarative RANGE partitioning.
    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        primary_key=True,
        nullable=False,
    )
    sku_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("sku_items.id", ondelete="CASCADE"),
        nullable=False,
    )
    warehouse_id: Mapped[str] = mapped_column(String(64), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    price_kopecks: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(
        String(8),
        nullable=False,
        default="RUB",
        server_default=text("'RUB'"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("NOW()"),
        index=True,
    )
