"""DTOs and enums for provider-neutral 3D generation."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ThreeDTaskLifecycleStatus(StrEnum):
    """Terminal and in-flight lifecycle states of a 3D generation task."""

    QUEUED = "QUEUED"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class ThreeDGenerationStage(StrEnum):
    """Fine-grained processing stages exposed while status is PROCESSING."""

    DRAFTING_MESH = "drafting_mesh"
    GENERATING_TEXTURES = "generating_textures"
    BAKING_MAPS = "baking_maps"


class ThreeDTaskStatusDTO(BaseModel):
    """Normalized task status returned by any ``BaseThreeDEngine`` adapter."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    status: ThreeDTaskLifecycleStatus
    progress_percent: int = Field(ge=0, le=100)
    result_urls: dict[str, str] = Field(default_factory=dict)
    stage: ThreeDGenerationStage | None = None
    error_message: str | None = None
    provider_task_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("result_urls")
    @classmethod
    def validate_result_urls(cls, value: dict[str, str]) -> dict[str, str]:
        for key, url in value.items():
            if not key.strip():
                raise ValueError("result_urls keys must be non-empty.")
            if not isinstance(url, str) or not url.strip():
                raise ValueError(f"result_urls[{key!r}] must be a non-empty URL string.")
        return value
