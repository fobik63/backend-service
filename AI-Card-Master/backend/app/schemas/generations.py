"""Pydantic v2 request/response schemas for the generations API."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.application.generation_options import (
    parse_engine_mode,
    parse_post_processing_mode,
)
from app.domain.generation import (
    GenerationEngineMode,
    GenerationJobStatus,
    GenerationPostProcessingMode,
    MarketplaceTextContent,
    SlideStatus,
)
from app.services.model_vto import BodyType, Ethnicity


class StrictAPIModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class GenerationCreateResponse(StrictAPIModel):
    task_id: UUID
    status: GenerationJobStatus
    status_url: str
    idempotent_replay: bool = False


class GenerationErrorResponse(StrictAPIModel):
    code: str
    message: str
    retryable: bool


class GenerationSlideResponse(StrictAPIModel):
    slide_key: str
    position: int
    status: SlideStatus
    progress: int
    provider_used: str | None = None
    result_url: str | None = None
    warning: str | None = None
    error: GenerationErrorResponse | None = None


class MarketplaceTextResponse(StrictAPIModel):
    title: str = Field(min_length=10, max_length=180)
    description: str = Field(min_length=1000, max_length=5000)
    characteristics: tuple[str, ...] = Field(min_length=3, max_length=12)

    @classmethod
    def from_domain(cls, content: MarketplaceTextContent) -> MarketplaceTextResponse:
        return cls(
            title=content.title,
            description=content.description,
            characteristics=content.characteristics,
        )


class GenerationStatusResponse(StrictAPIModel):
    task_id: UUID
    status: GenerationJobStatus
    progress: int
    provider_used: str | None = None
    warning: str | None = None
    archive_url: str | None = None
    marketplace_text: MarketplaceTextResponse | None = None
    slides: tuple[GenerationSlideResponse, ...]
    error: GenerationErrorResponse | None = None
    created_at: str
    updated_at: str
    completed_at: str | None = None


class GenerationHistoryItemResponse(StrictAPIModel):
    task_id: UUID
    status: GenerationJobStatus
    progress: int
    product_category: str | None = None
    slide_count: int = Field(default=0, ge=0)
    thumbnail_url: str | None = None
    thumbnail_mime_type: str | None = None
    thumbnail_size_bytes: int | None = Field(default=None, ge=1, le=100 * 1024)
    archive_status: Literal["available", "expired", "pending", "unavailable", "deleted"]
    archive_url: str | None = None
    archive_expires_at: str | None = None
    provider_used: str | None = None
    warning: str | None = None
    created_at: str
    completed_at: str | None = None


class GenerationForm(StrictAPIModel):
    """Strictly validated non-file fields from multipart input."""

    product_category: str | None = Field(default=None, max_length=128)
    engine_mode: GenerationEngineMode = GenerationEngineMode.STANDARD
    post_processing_mode: GenerationPostProcessingMode = GenerationPostProcessingMode.FAST
    apply_text_overlays: bool = False
    overlay_texts: dict[str, str] = Field(default_factory=dict)
    preserve_subject: bool = True
    editor_cover_only: bool = False
    style_prompt: str | None = Field(default=None, max_length=2000)

    @field_validator("engine_mode", mode="before")
    @classmethod
    def _parse_engine_mode(cls, value: object) -> GenerationEngineMode:
        return parse_engine_mode(value)

    @field_validator("post_processing_mode", mode="before")
    @classmethod
    def _parse_post_processing_mode(cls, value: object) -> GenerationPostProcessingMode:
        return parse_post_processing_mode(value)

    @field_validator("product_category")
    @classmethod
    def clean_category(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None

    @field_validator("style_prompt")
    @classmethod
    def clean_style_prompt(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = " ".join(value.strip().split())
        return cleaned or None

    @field_validator("overlay_texts")
    @classmethod
    def validate_overlay_texts(cls, value: dict[str, str]) -> dict[str, str]:
        allowed = {"cover", "macro", "lifestyle", "technical", "trust"}
        if set(value) - allowed:
            raise ValueError("overlay_texts contains an unknown slide key.")
        cleaned: dict[str, str] = {}
        for key, text in value.items():
            normalised = text.strip()
            if not normalised or len(normalised) > 300:
                raise ValueError("Each overlay text must contain 1-300 characters.")
            cleaned[key] = normalised
        return cleaned


class ModelModeRequest(StrictAPIModel):
    """JSON contract for clothing virtual try-on on an AI model."""

    source_image_object_key: str = Field(
        min_length=16,
        max_length=1024,
        pattern=r"^[A-Za-z0-9._/\-]+$",
        description="Private S3 object key of the uploaded clothing source image.",
    )
    height_cm: int = Field(ge=140, le=220, description="AI model height in centimeters.")
    body_type: BodyType
    ethnicity: Ethnicity
    engine_mode: GenerationEngineMode = GenerationEngineMode.STANDARD
    post_processing_mode: GenerationPostProcessingMode = GenerationPostProcessingMode.FAST
    background: str | None = Field(default=None, min_length=3, max_length=160)
    pose: str | None = Field(default=None, min_length=3, max_length=160)

    @field_validator("engine_mode", mode="before")
    @classmethod
    def _parse_engine_mode(cls, value: object) -> GenerationEngineMode:
        return parse_engine_mode(value)

    @field_validator("post_processing_mode", mode="before")
    @classmethod
    def _parse_post_processing_mode(cls, value: object) -> GenerationPostProcessingMode:
        return parse_post_processing_mode(value)

    @field_validator("source_image_object_key")
    @classmethod
    def validate_source_key(cls, value: str) -> str:
        cleaned = value.strip().replace("\\", "/")
        parts = [part for part in cleaned.split("/") if part]
        if cleaned.startswith("/") or "//" in cleaned or ".." in parts:
            raise ValueError("source_image_object_key must be a safe relative S3 key.")
        if not cleaned.lower().endswith((".jpg", ".jpeg", ".png", ".webp")):
            raise ValueError("source_image_object_key must point to JPEG, PNG, or WebP.")
        return cleaned

    @field_validator("background", "pose")
    @classmethod
    def clean_optional_prompt(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = " ".join(value.strip().split())
        return cleaned or None
