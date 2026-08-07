"""Ports for Custom Brand LoRA persistence and training providers."""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from app.domain.brand_lora import (
    BrandLoraStatus,
    BrandLoraView,
    BrandStyleFilter,
    LoraTrainingPollResult,
    LoraTrainingStartResult,
)


class BrandLoraPersistencePort(Protocol):
    """Storage operations for brand LoRA profiles and references."""

    async def create_profile(
        self,
        *,
        user_id: UUID,
        name: str,
        trigger_word: str,
        notes: str | None,
        coins_charged: int,
        references: tuple[tuple[str, str, int], ...],
    ) -> BrandLoraView:
        """Persist a queued profile with S3 reference keys.

        ``references`` items are ``(object_key, mime_type, size_bytes)``.
        """

    async def get_for_user(
        self, *, user_id: UUID, profile_id: UUID, include_references: bool = False
    ) -> BrandLoraView | None:
        """Load one profile owned by the user."""

    async def get(self, *, profile_id: UUID, include_references: bool = True) -> BrandLoraView | None:
        """Load a profile by id (worker path)."""

    async def list_for_user(
        self, *, user_id: UUID, limit: int = 50
    ) -> tuple[BrandLoraView, ...]:
        """List non-archived profiles for the user (newest first)."""

    async def get_active_filter(self, *, user_id: UUID) -> BrandStyleFilter | None:
        """Return the active ready brand filter for generation injection."""

    async def mark_training_started(
        self,
        *,
        profile_id: UUID,
        provider_training_id: str,
        brand_style_prompt: str,
        status: BrandLoraStatus = BrandLoraStatus.TRAINING,
        progress: int = 5,
    ) -> BrandLoraView:
        """Attach provider training id after kickoff."""

    async def mark_progress(
        self,
        *,
        profile_id: UUID,
        status: BrandLoraStatus,
        progress: int,
        error_message: str | None = None,
    ) -> BrandLoraView:
        """Update training progress / intermediate status."""

    async def mark_ready(
        self,
        *,
        profile_id: UUID,
        brand_style_prompt: str,
        lora_weights_url: str | None,
        provider_version_id: str | None,
        activate: bool = True,
    ) -> BrandLoraView:
        """Mark training complete and optionally activate the filter."""

    async def mark_failed(self, *, profile_id: UUID, error_message: str) -> BrandLoraView:
        """Mark training as failed and refund path is handled by the service."""

    async def set_active(
        self, *, user_id: UUID, profile_id: UUID, active: bool
    ) -> BrandLoraView:
        """Activate or deactivate a ready profile (one active per user)."""

    async def archive(self, *, user_id: UUID, profile_id: UUID) -> BrandLoraView:
        """Soft-delete / archive a profile."""

    async def list_active_training_ids(self, *, limit: int) -> tuple[UUID, ...]:
        """Profiles in queued/training that need provider polling."""

    async def debit_coins(self, *, user_id: UUID, amount: int) -> int:
        """Atomically debit AI-coins; return new balance."""

    async def refund_coins(self, *, user_id: UUID, amount: int) -> int:
        """Refund AI-coins after a failed training run."""


class LoraTrainingProviderPort(Protocol):
    """External LoRA fine-tune provider (Replicate) or synthetic fallback."""

    @property
    def name(self) -> str:
        """Provider identifier for logs."""

    async def start_training(
        self,
        *,
        trigger_word: str,
        brand_name: str,
        notes: str | None,
        reference_object_keys: tuple[str, ...],
        dataset_zip_bytes: bytes | None = None,
    ) -> LoraTrainingStartResult:
        """Kick off training; return provider training id."""

    async def poll_training(self, *, training_id: str) -> LoraTrainingPollResult:
        """Poll provider status / weights URL."""
