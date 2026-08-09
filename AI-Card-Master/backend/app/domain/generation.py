"""Strict domain contracts for the asynchronous generation state machine."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator


class GenerationJobStatus(StrEnum):
    """Lifecycle states exposed to clients and persisted in PostgreSQL."""

    QUEUED = "queued"
    SUBMITTING = "submitting"
    WAITING_WEBHOOK = "waiting_webhook"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class SlideStatus(StrEnum):
    """Lifecycle of one slide inside a five-slide generation."""

    QUEUED = "queued"
    SUBMITTING = "submitting"
    WAITING_WEBHOOK = "waiting_webhook"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class GenerationProvider(StrEnum):
    """Stable provider identifiers used by adapters and persistence."""

    MIDJOURNEY = "midjourney"
    STABLE_DIFFUSION = "stable_diffusion"


class GenerationEngineMode(StrEnum):
    """Client-selected image engine profile."""

    STANDARD = "standard"
    PREMIUM = "premium"


class GenerationPostProcessingMode(StrEnum):
    """Client-selected post-processing tier."""

    FAST = "fast"
    HD_FACE_FIX = "hd_face_fix"


class GenerationErrorCode(StrEnum):
    """Sanitised error categories safe to return to API clients."""

    VALIDATION = "validation_error"
    CONFIGURATION = "provider_not_configured"
    TRANSIENT = "provider_temporarily_unavailable"
    RATE_LIMIT = "provider_rate_limited"
    MODERATION = "content_moderated"
    PERMANENT = "generation_failed"
    STORAGE = "storage_unavailable"
    INTERNAL = "internal_error"


class OutboxEventType(StrEnum):
    """Commands delivered durably to Celery through the outbox."""

    SUBMIT_JOB = "submit_job"
    PROCESS_WEBHOOK = "process_webhook"
    FINALIZE_JOB = "finalize_job"
    RECOVER_JOB = "recover_job"


class DomainModel(BaseModel):
    """Shared strict Pydantic v2 configuration for domain boundaries."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        validate_default=True,
    )


class GenerationErrorInfo(DomainModel):
    """Public, provider-neutral generation error."""

    code: GenerationErrorCode
    message: str = Field(min_length=1, max_length=500)
    retryable: bool = False
    attempts: int = Field(default=0, ge=0, le=100)


class MarketplaceTextContent(DomainModel):
    """AI-generated marketplace selling copy for WB/Ozon product cards."""

    title: str = Field(min_length=10, max_length=180)
    description: str = Field(min_length=800, max_length=5000)
    characteristics: tuple[str, ...] = Field(min_length=3, max_length=12)

    @field_validator("title", "description")
    @classmethod
    def clean_text(cls, value: str) -> str:
        cleaned = " ".join(value.strip().split())
        if not cleaned:
            raise ValueError("Text value cannot be empty.")
        return cleaned

    @field_validator("characteristics")
    @classmethod
    def clean_characteristics(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        cleaned = tuple(" ".join(item.strip().split()) for item in value if item.strip())
        if len(cleaned) < 3:
            raise ValueError("At least three characteristics are required.")
        return cleaned


class ProviderSubmission(DomainModel):
    """Result returned by a submit-only asynchronous provider call."""

    provider: str = Field(min_length=1, max_length=64)
    external_job_id: str = Field(min_length=1, max_length=512)
    reply_ref: str = Field(min_length=1, max_length=1024)
    initial_status: str = Field(default="created", min_length=1, max_length=64)
    # Optional provider invoice fields (Midjourney credits / USD). When set,
    # cost analytics prefers these over the flat settings estimate (C4).
    provider_cost_usd: Decimal | None = None
    provider_credits: float | None = Field(default=None, ge=0)
    cost_metadata: dict[str, Any] = Field(default_factory=dict)


class ProviderWebhookEvent(DomainModel):
    """Normalised webhook event produced by a provider adapter."""

    provider: str = Field(min_length=1, max_length=64)
    event_id: str = Field(min_length=1, max_length=512)
    external_job_id: str | None = Field(default=None, max_length=512)
    reply_ref: str = Field(min_length=1, max_length=1024)
    status: str = Field(min_length=1, max_length=64)
    progress: int = Field(default=0, ge=0, le=100)
    result_url: HttpUrl | None = None
    error_message: str | None = Field(default=None, max_length=1000)
    raw_payload: dict[str, Any] = Field(default_factory=dict)

    @field_validator("status")
    @classmethod
    def normalise_status(cls, value: str) -> str:
        return value.strip().lower()

    @property
    def is_terminal_success(self) -> bool:
        return self.status in {"completed", "done", "finished", "success"}

    @property
    def is_terminal_failure(self) -> bool:
        return self.status in {"failed", "error", "cancelled", "moderated"}


class SlideStatusResult(DomainModel):
    """Client-safe status for one generated slide."""

    slide_key: str = Field(min_length=1, max_length=64)
    position: int = Field(ge=1, le=100)
    status: SlideStatus
    provider_used: str | None = Field(default=None, max_length=64)
    progress: int = Field(default=0, ge=0, le=100)
    result_url: HttpUrl | None = None
    warning: str | None = Field(default=None, max_length=500)
    error: GenerationErrorInfo | None = None


class GenerationStatus(DomainModel):
    """Complete polling payload independent of FastAPI and SQLAlchemy."""

    task_id: UUID
    status: GenerationJobStatus
    progress: int = Field(default=0, ge=0, le=100)
    provider_used: str | None = Field(default=None, max_length=64)
    warning: str | None = Field(default=None, max_length=500)
    archive_url: HttpUrl | None = None
    marketplace_text: MarketplaceTextContent | None = None
    slides: tuple[SlideStatusResult, ...] = ()
    error: GenerationErrorInfo | None = None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None


class SlideWorkItem(DomainModel):
    """Persistence-independent slide command consumed by use cases."""

    id: UUID
    slide_key: str = Field(min_length=1, max_length=64)
    position: int = Field(ge=1, le=100)
    status: SlideStatus
    selected_style: str = Field(min_length=1, max_length=500)
    prompt: str = Field(min_length=1, max_length=8000)
    provider_used: str | None = Field(default=None, max_length=64)
    result_object_key: str | None = Field(default=None, max_length=1024)
    result_mime_type: str | None = Field(default=None, max_length=128)
    attempts: int = Field(default=0, ge=0, le=100)


class GenerationWorkItem(DomainModel):
    """Parent work command loaded from PostgreSQL."""

    id: UUID
    user_id: UUID
    status: GenerationJobStatus
    input_object_key: str = Field(min_length=1, max_length=1024)
    product_category: str | None = Field(default=None, max_length=128)
    subscription_status: str = Field(min_length=1, max_length=32)
    engine_mode: GenerationEngineMode = GenerationEngineMode.STANDARD
    post_processing_mode: GenerationPostProcessingMode = GenerationPostProcessingMode.FAST
    apply_text_overlays: bool = False
    overlay_texts: dict[str, str] = Field(default_factory=dict)
    marketplace_text: MarketplaceTextContent | None = None
    slides: tuple[SlideWorkItem, ...]


class AttemptWorkItem(DomainModel):
    """Provider attempt resolved from a signed callback reference."""

    id: UUID
    slide_id: UUID
    job_id: UUID
    provider_name: str = Field(min_length=1, max_length=64)
    attempt_number: int = Field(ge=1, le=100)
    external_job_id: str | None = Field(default=None, max_length=512)
    reply_ref: str = Field(min_length=1, max_length=1024)
    abandoned: bool = False
    slide_status: SlideStatus


class OutboxMessage(DomainModel):
    """Message claimed from the transactional outbox."""

    id: UUID
    event_type: OutboxEventType
    aggregate_id: UUID
    payload: dict[str, Any]
