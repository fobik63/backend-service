"""Ports for Claude 4.7 Vision & Chain-of-Thought reasoning."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol
from uuid import UUID

from app.domain.claude_reasoning import (
    ClaudeReasoningJobStatus,
    ClaudeReasoningJobView,
    CompetitorTextContext,
    ReasoningStageResult,
    VisionStageResult,
)


class ClaudeReasoningPersistencePort(Protocol):
    """Durable storage for async Claude reasoning jobs."""

    async def create_job(
        self,
        *,
        user_id: UUID,
        image_object_keys: tuple[str, ...],
        text_context: dict[str, Any],
        model_name: str,
        idempotency_key: str | None = None,
    ) -> ClaudeReasoningJobView:
        """Persist a queued reasoning job."""

    async def find_idempotent_job(
        self, *, user_id: UUID, idempotency_key: str
    ) -> ClaudeReasoningJobView | None:
        """Return an existing job created with the same idempotency key."""

    async def get_job_for_user(
        self, *, user_id: UUID, job_id: UUID
    ) -> ClaudeReasoningJobView | None:
        """Load a job owned by the user."""

    async def get_job(self, *, job_id: UUID) -> ClaudeReasoningJobView | None:
        """Load a job by id (worker path)."""

    async def mark_status(
        self,
        *,
        job_id: UUID,
        status: ClaudeReasoningJobStatus,
        celery_task_id: str | None = None,
        error_message: str | None = None,
        completed_at: datetime | None = None,
    ) -> ClaudeReasoningJobView:
        """Update job lifecycle status."""

    async def save_vision_result(
        self,
        *,
        job_id: UUID,
        vision_result: dict[str, Any],
        input_tokens_delta: int = 0,
        output_tokens_delta: int = 0,
    ) -> ClaudeReasoningJobView:
        """Persist stage-1 Vision JSON and advance status."""

    async def save_final_result(
        self,
        *,
        job_id: UUID,
        reasoning_result: dict[str, Any],
        final_result: dict[str, Any],
        input_tokens_delta: int = 0,
        output_tokens_delta: int = 0,
    ) -> ClaudeReasoningJobView:
        """Persist stage-2 + merged CoT result and mark completed."""


class ClaudeVisionReasoningPort(Protocol):
    """Anthropic Claude 4.7 Vision + JSON Mode adapter."""

    @property
    def model_name(self) -> str:
        """Configured Claude model identifier."""

    async def analyze_visual_triggers(
        self,
        *,
        images: tuple[tuple[bytes, str], ...],
        product_category: str | None,
    ) -> tuple[VisionStageResult, int, int]:
        """Stage 1: Vision analysis → structured visual triggers.

        Returns (result, input_tokens, output_tokens).
        """

    async def align_triggers_with_text(
        self,
        *,
        vision: VisionStageResult,
        text_context: CompetitorTextContext,
    ) -> tuple[ReasoningStageResult, int, int]:
        """Stage 2: Chain-of-Thought text alignment.

        Returns (result, input_tokens, output_tokens).
        """

    async def aclose(self) -> None:
        """Release HTTP resources."""
