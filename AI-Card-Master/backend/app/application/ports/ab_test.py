"""Ports for Automated A/B Testing Logic."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol
from uuid import UUID

from app.domain.ab_test import (
    AbCreativeStrategy,
    AbExperimentStatus,
    AbExperimentView,
    AbProductBrief,
    AbVariantHypothesis,
    AbVariantMetrics,
    AbVariantStatus,
    AbVariantView,
)


class AbTestPersistencePort(Protocol):
    """Durable storage for A/B experiments and variants."""

    async def create_experiment(
        self,
        *,
        user_id: UUID,
        marketplace: str,
        niche_key: str,
        sku: str,
        nm_id: str | None,
        campaign_id: str | None,
        product_payload: dict[str, Any],
        config: dict[str, Any],
        model_name: str,
        strategies: tuple[AbCreativeStrategy, ...],
        idempotency_key: str | None = None,
    ) -> AbExperimentView:
        """Persist a queued experiment with pending variant slots."""

    async def find_idempotent_experiment(
        self, *, user_id: UUID, idempotency_key: str
    ) -> AbExperimentView | None:
        """Return an existing experiment created with the same idempotency key."""

    async def get_experiment_for_user(
        self, *, user_id: UUID, experiment_id: UUID
    ) -> AbExperimentView | None:
        """Load an experiment owned by the user (with variants)."""

    async def get_experiment(
        self, *, experiment_id: UUID, include_variants: bool = True
    ) -> AbExperimentView | None:
        """Load an experiment by id (worker path)."""

    async def list_experiments_for_user(
        self, *, user_id: UUID, limit: int = 20
    ) -> tuple[AbExperimentView, ...]:
        """List recent experiments for the seller."""

    async def list_active_measuring(
        self, *, limit: int = 50
    ) -> tuple[AbExperimentView, ...]:
        """Experiments currently measuring CTR (for Celery beat)."""

    async def list_due_for_resolution(
        self, *, now: datetime, limit: int = 50
    ) -> tuple[AbExperimentView, ...]:
        """Measuring experiments whose window has ended."""

    async def mark_status(
        self,
        *,
        experiment_id: UUID,
        status: AbExperimentStatus,
        celery_task_id: str | None = None,
        error_message: str | None = None,
        completed_at: datetime | None = None,
        measurement_started_at: datetime | None = None,
        measurement_ends_at: datetime | None = None,
        winner_variant_id: UUID | None = None,
        resolution_result: dict[str, Any] | None = None,
    ) -> AbExperimentView:
        """Update experiment lifecycle fields."""

    async def save_hypotheses(
        self,
        *,
        experiment_id: UUID,
        hypotheses: list[dict[str, Any]],
        input_tokens_delta: int = 0,
        output_tokens_delta: int = 0,
    ) -> AbExperimentView:
        """Persist generated hypotheses onto variants + experiment payload."""

    async def update_variant(
        self,
        *,
        variant_id: UUID,
        status: AbVariantStatus | None = None,
        ads_creative_id: str | None = None,
        ads_campaign_id: str | None = None,
        marketplace_media_id: str | None = None,
        metrics: AbVariantMetrics | None = None,
        error_message: str | None = None,
        clear_error: bool = False,
    ) -> AbVariantView:
        """Patch one variant (publish / metrics / resolution)."""

    async def save_final_resolution(
        self,
        *,
        experiment_id: UUID,
        resolution_result: dict[str, Any],
        winner_variant_id: UUID | None,
        winner_status: AbVariantStatus,
        loser_ids: list[UUID],
        deleted_ids: list[UUID],
    ) -> AbExperimentView:
        """Mark winner/losers/deleted and complete the experiment."""


class AbHypothesisGenerationPort(Protocol):
    """Claude JSON adapter for three creative hypotheses."""

    @property
    def model_name(self) -> str:
        """Configured Claude model identifier."""

    async def generate_ab_hypotheses(
        self,
        *,
        product: AbProductBrief,
        user_id: UUID | None = None,
        experiment_id: UUID | None = None,
    ) -> tuple[tuple[AbVariantHypothesis, ...], int, int]:
        """Return (exactly 3 hypotheses, input_tokens, output_tokens)."""

    async def aclose(self) -> None:
        """Release HTTP resources."""


class MarketplaceAdsPort(Protocol):
    """Advertising cabinet: publish creatives, fetch CTR, delete losers."""

    async def publish_creative(
        self,
        *,
        credentials: dict[str, str],
        product: AbProductBrief,
        hypothesis: AbVariantHypothesis,
        campaign_id: str | None = None,
    ) -> dict[str, str]:
        """Publish one creative. Returns ids: creative_id, campaign_id, media_id."""

    async def fetch_creative_metrics(
        self,
        *,
        credentials: dict[str, str],
        creative_id: str,
        campaign_id: str | None = None,
    ) -> AbVariantMetrics:
        """Pull impressions / clicks / CTR for one creative."""

    async def promote_winner(
        self,
        *,
        credentials: dict[str, str],
        creative_id: str,
        campaign_id: str | None = None,
        product: AbProductBrief | None = None,
    ) -> str:
        """Keep winner as the primary creative; return kept creative id."""

    async def delete_creative(
        self,
        *,
        credentials: dict[str, str],
        creative_id: str,
        campaign_id: str | None = None,
    ) -> bool:
        """Remove a losing creative from the ads cabinet."""

    async def aclose(self) -> None:
        """Release HTTP resources."""


class AbCredentialsPort(Protocol):
    """Load decrypted seller/ads credentials for a marketplace platform."""

    async def get_ads_credentials(
        self, *, user_id: UUID, platform: str
    ) -> dict[str, str]:
        """Return plaintext credential map (api_token, client_id, ...)."""
