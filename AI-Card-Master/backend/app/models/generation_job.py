"""Durable ORM state for queued generation and provider webhooks."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.domain.generation import GenerationJobStatus, OutboxEventType, SlideStatus
from app.models.base import Base


class GenerationJob(Base):
    """Parent aggregate returned to clients as a stable public task id."""

    __tablename__ = "generation_jobs"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "idempotency_key",
            name="uq_generation_jobs_user_idempotency",
        ),
        CheckConstraint(
            "progress >= 0 AND progress <= 100", name="ck_generation_jobs_progress"
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
        default=GenerationJobStatus.QUEUED.value,
        server_default=text("'queued'"),
        index=True,
    )
    progress: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
    )
    product_category: Mapped[str | None] = mapped_column(String(128), nullable=True)
    subscription_status: Mapped[str] = mapped_column(String(32), nullable=False)
    input_object_key: Mapped[str] = mapped_column(String(1024), nullable=False)
    archive_object_key: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    apply_text_overlays: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("false"),
    )
    overlay_texts: Mapped[dict[str, str] | None] = mapped_column(JSONB, nullable=True)
    provider_used: Mapped[str | None] = mapped_column(String(64), nullable=True)
    warning: Mapped[str | None] = mapped_column(String(500), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_retryable: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("false"),
    )
    coin_charged: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("false"),
    )
    coin_refunded: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("false"),
    )
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
        onupdate=text("CURRENT_TIMESTAMP"),
    )
    heartbeat_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    deadline_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    user = relationship("User", back_populates="generation_jobs")
    slides = relationship(
        "GenerationSlide",
        back_populates="job",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="GenerationSlide.position",
    )


class GenerationSlide(Base):
    """Current state of one slide in a generation series."""

    __tablename__ = "generation_slides"
    __table_args__ = (
        UniqueConstraint("job_id", "slide_key", name="uq_generation_slides_job_key"),
        UniqueConstraint(
            "job_id", "position", name="uq_generation_slides_job_position"
        ),
        CheckConstraint(
            "progress >= 0 AND progress <= 100",
            name="ck_generation_slides_progress",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
        server_default=text("gen_random_uuid()"),
    )
    job_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("generation_jobs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    slide_key: Mapped[str] = mapped_column(String(64), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=SlideStatus.QUEUED.value,
        server_default=text("'queued'"),
        index=True,
    )
    progress: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
    )
    selected_style: Mapped[str] = mapped_column(String(500), nullable=False)
    prompt_used: Mapped[str] = mapped_column(Text, nullable=False)
    provider_used: Mapped[str | None] = mapped_column(String(64), nullable=True)
    result_object_key: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    result_mime_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    warning: Mapped[str | None] = mapped_column(String(500), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_retryable: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("false"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
        onupdate=text("CURRENT_TIMESTAMP"),
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    job = relationship("GenerationJob", back_populates="slides")
    attempts = relationship(
        "GenerationProviderAttempt",
        back_populates="slide",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="GenerationProviderAttempt.attempt_number",
    )


class GenerationProviderAttempt(Base):
    """Immutable-enough provider attempt used to handle late callbacks safely."""

    __tablename__ = "generation_provider_attempts"
    __table_args__ = (
        UniqueConstraint(
            "slide_id",
            "attempt_number",
            name="uq_generation_provider_attempt_slide_number",
        ),
        UniqueConstraint("reply_ref", name="uq_generation_provider_attempt_reply_ref"),
        UniqueConstraint(
            "provider_name",
            "external_job_id",
            name="uq_generation_provider_attempt_external",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
        server_default=text("gen_random_uuid()"),
    )
    slide_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("generation_slides.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    provider_name: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    external_job_id: Mapped[str | None] = mapped_column(
        String(512), nullable=True, index=True
    )
    reply_ref: Mapped[str] = mapped_column(String(1024), nullable=False)
    status: Mapped[str] = mapped_column(
        String(64), nullable=False, server_default=text("'created'")
    )
    progress: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    result_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    abandoned: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("false"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
        onupdate=text("CURRENT_TIMESTAMP"),
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    slide = relationship("GenerationSlide", back_populates="attempts")


class GenerationWebhookEvent(Base):
    """Deduplicated webhook receipt; payload is retained for recovery."""

    __tablename__ = "generation_webhook_events"
    __table_args__ = (
        UniqueConstraint(
            "provider_name",
            "event_id",
            name="uq_generation_webhook_provider_event",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
        server_default=text("gen_random_uuid()"),
    )
    provider_name: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    event_id: Mapped[str] = mapped_column(String(512), nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    raw_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    processed: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("false"),
        index=True,
    )
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    processed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class GenerationOutbox(Base):
    """Transactional messages published to Celery by a periodic dispatcher."""

    __tablename__ = "generation_outbox"

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
        server_default=text("gen_random_uuid()"),
    )
    event_type: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default=OutboxEventType.SUBMIT_JOB.value,
        index=True,
    )
    aggregate_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), nullable=False, index=True
    )
    deduplication_key: Mapped[str] = mapped_column(
        String(512), unique=True, nullable=False
    )
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="pending",
        server_default=text("'pending'"),
        index=True,
    )
    attempts: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
    )
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
        index=True,
    )
    locked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    processed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )
