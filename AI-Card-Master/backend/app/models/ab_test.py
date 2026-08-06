"""ORM models for Automated A/B Testing experiments and variants."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class AbTestExperiment(Base):
    """Aggregate root: 3 main-card hypotheses → CTR measure → keep winner."""

    __tablename__ = "ab_test_experiments"
    __table_args__ = (
        Index("ix_ab_test_experiments_user_status", "user_id", "status"),
        Index("ix_ab_test_experiments_measuring_ends", "status", "measurement_ends_at"),
        Index(
            "uq_ab_test_experiments_user_idempotency",
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
    celery_task_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    model_name: Mapped[str] = mapped_column(String(128), nullable=False)
    marketplace: Mapped[str] = mapped_column(String(32), nullable=False)
    niche_key: Mapped[str] = mapped_column(String(128), nullable=False)
    sku: Mapped[str] = mapped_column(String(64), nullable=False)
    nm_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    campaign_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    product_payload: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    config: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    hypotheses_payload: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    resolution_result: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    winner_variant_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        nullable=True,
    )
    measurement_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    measurement_ends_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    input_tokens: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
    )
    output_tokens: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("NOW()"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("NOW()"),
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    variants = relationship(
        "AbTestVariant",
        back_populates="experiment",
        cascade="all, delete-orphan",
        order_by="AbTestVariant.position",
    )


class AbTestVariant(Base):
    """One of three creative strategies inside an A/B experiment."""

    __tablename__ = "ab_test_variants"
    __table_args__ = (
        Index("ix_ab_test_variants_experiment_status", "experiment_id", "status"),
        Index(
            "uq_ab_test_variants_experiment_position",
            "experiment_id",
            "position",
            unique=True,
        ),
        Index(
            "uq_ab_test_variants_experiment_strategy",
            "experiment_id",
            "strategy",
            unique=True,
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
        server_default=text("gen_random_uuid()"),
    )
    experiment_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("ab_test_experiments.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    strategy: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="pending",
        server_default=text("'pending'"),
        index=True,
    )
    title: Mapped[str | None] = mapped_column(String(200), nullable=True)
    main_image_brief: Mapped[str | None] = mapped_column(Text, nullable=True)
    offer_hook: Mapped[str | None] = mapped_column(String(300), nullable=True)
    headline: Mapped[str | None] = mapped_column(String(200), nullable=True)
    rationale: Mapped[str | None] = mapped_column(String(500), nullable=True)
    prompt_for_generator: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    ads_creative_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    ads_campaign_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    marketplace_media_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    impressions: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
    )
    clicks: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
    )
    ctr_pct: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        default=0.0,
        server_default=text("0"),
    )
    spend: Mapped[float | None] = mapped_column(Float, nullable=True)
    metrics_sampled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("NOW()"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("NOW()"),
    )

    experiment = relationship("AbTestExperiment", back_populates="variants")
