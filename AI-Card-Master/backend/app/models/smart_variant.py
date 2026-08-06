"""ORM models for Smart Variant Sync jobs and color items."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
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
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class SmartVariantSync(Base):
    """Aggregate root for a one-photo → N-color fabric recolor run."""

    __tablename__ = "smart_variant_syncs"
    __table_args__ = (
        Index("ix_smart_variant_syncs_user_status", "user_id", "status"),
        Index(
            "uq_smart_variant_syncs_user_idempotency",
            "user_id",
            "idempotency_key",
            unique=True,
            postgresql_where=text("idempotency_key IS NOT NULL"),
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
        server_default=text("gen_random_uuid()"),
    )
    user_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    idempotency_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="queued",
        server_default=text("'queued'"),
        index=True,
    )
    product_category: Mapped[str | None] = mapped_column(String(128), nullable=True)
    engine_mode: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="standard",
        server_default=text("'standard'"),
    )
    post_processing_mode: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="fast",
        server_default=text("'fast'"),
    )
    apply_text_overlays: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("false"),
    )
    source_image_object_key: Mapped[str] = mapped_column(String(1024), nullable=False)
    source_retention_status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="available",
        server_default=text("'available'"),
        index=True,
    )
    source_mime_type: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default="image/jpeg",
        server_default=text("'image/jpeg'"),
    )
    total_items: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
    )
    completed_items: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
    )
    failed_items: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
    )
    skipped_items: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
    )
    notify_telegram: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default=text("true"),
    )
    notify_push: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default=text("true"),
    )
    telegram_notified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=None,
    )
    push_notified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=None,
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
        index=True,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=None,
    )

    items = relationship(
        "SmartVariantItem",
        back_populates="sync",
        cascade="all, delete-orphan",
        order_by="SmartVariantItem.position",
    )


class SmartVariantItem(Base):
    """One target color inside a Smart Variant Sync job."""

    __tablename__ = "smart_variant_items"
    __table_args__ = (
        Index("ix_smart_variant_items_sync_status", "sync_id", "status"),
        Index(
            "uq_smart_variant_items_sync_position",
            "sync_id",
            "position",
            unique=True,
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
        server_default=text("gen_random_uuid()"),
    )
    sync_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("smart_variant_syncs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    color_name: Mapped[str] = mapped_column(String(64), nullable=False)
    color_hex: Mapped[str | None] = mapped_column(String(7), nullable=True)
    color_slug: Mapped[str] = mapped_column(String(96), nullable=False)
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="pending",
        server_default=text("'pending'"),
        index=True,
    )
    recolored_object_key: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    generation_job_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("generation_jobs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )

    sync = relationship("SmartVariantSync", back_populates="items")
