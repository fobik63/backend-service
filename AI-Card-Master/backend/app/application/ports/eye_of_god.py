"""Ports for the stock-parser ↔ «Глаз Бога» (Claude 4.7 Vision) bridge."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol
from uuid import UUID

from app.domain.eye_of_god import (
    EyeOfGodJobStatus,
    EyeOfGodJobView,
    MoneyConfirmedVisionResult,
    SalesSpikeSignal,
)


class EyeOfGodPersistencePort(Protocol):
    """Durable storage for spike → Vision → money-trigger JSON jobs."""

    async def create_job(
        self,
        *,
        spike: SalesSpikeSignal,
        model_name: str,
        idempotency_key: str | None = None,
    ) -> EyeOfGodJobView:
        """Persist a queued Eye-of-God job from a sales-spike signal."""

    async def find_recent_job_for_sku(
        self,
        *,
        sku_id: UUID,
        since: datetime,
    ) -> EyeOfGodJobView | None:
        """Cooldown lookup: avoid re-firing Claude within the spike window."""

    async def find_idempotent_job(
        self, *, idempotency_key: str
    ) -> EyeOfGodJobView | None:
        """Return an existing job created with the same idempotency key."""

    async def get_job(self, *, job_id: UUID) -> EyeOfGodJobView | None:
        """Load a job by id (worker path)."""

    async def mark_status(
        self,
        *,
        job_id: UUID,
        status: EyeOfGodJobStatus,
        celery_task_id: str | None = None,
        error_message: str | None = None,
        completed_at: datetime | None = None,
    ) -> EyeOfGodJobView:
        """Update job lifecycle status."""

    async def save_money_trigger_result(
        self,
        *,
        job_id: UUID,
        vision_result: dict[str, Any],
        money_trigger_config: dict[str, Any],
        image_urls: list[str] | None = None,
        input_tokens_delta: int = 0,
        output_tokens_delta: int = 0,
    ) -> EyeOfGodJobView:
        """Persist Vision JSON + «Подтвержденный деньгами триггер» config."""


class EyeOfGodVisionPort(Protocol):
    """Claude 4.7 Vision adapter for money-confirmed conversion analysis."""

    @property
    def model_name(self) -> str:
        """Configured Claude model identifier."""

    async def analyze_money_confirmed_trigger(
        self,
        *,
        sku: str,
        title: str | None,
        marketplace: str,
        growth_ratio: float,
        recent_avg_daily_sales: float,
        baseline_avg_daily_sales: float,
        recent_window_days: int,
        images: tuple[tuple[bytes, str], ...],
        user_id: UUID | None = None,
        job_id: UUID | None = None,
    ) -> tuple[MoneyConfirmedVisionResult, int, int]:
        """Analyze current SKU photo(s) for new conversion elements.

        Returns (vision_result, input_tokens, output_tokens).
        """

    async def aclose(self) -> None:
        """Release HTTP resources."""


class SkuCardImagePort(Protocol):
    """Fetch the current marketplace card photo for a spiked SKU."""

    async def fetch_current_images(
        self,
        *,
        marketplace: str,
        article: str,
        product_url: str | None = None,
        preferred_urls: tuple[str, ...] = (),
        max_images: int = 3,
    ) -> tuple[tuple[bytes, str, str], ...]:
        """Return ((bytes, mime_type, source_url), ...) for Vision."""


class EyeOfGodTriggerPort(Protocol):
    """Fire-and-forget enqueue from the parser process into Eye of God."""

    def enqueue_sales_spike(self, *, job_id: UUID) -> str:
        """Publish Celery task; return celery task id."""
