"""Ports for Direct Export: credentials, generation assets, and seller APIs."""

from __future__ import annotations

from typing import Any, Protocol
from uuid import UUID

from app.domain.export import (
    ExportCardSource,
    ExportResultView,
    ExportStatus,
    ImageAssetMeta,
    MarketplaceCredentialView,
    MarketplacePlatform,
)


class ExportPersistencePort(Protocol):
    """Storage for encrypted marketplace credentials and export history."""

    async def upsert_credentials(
        self,
        *,
        user_id: UUID,
        platform: MarketplacePlatform,
        ciphertext: str,
        label: str | None,
    ) -> MarketplaceCredentialView:
        """Create or replace encrypted credentials for a platform."""

    async def get_credentials_ciphertext(
        self, *, user_id: UUID, platform: MarketplacePlatform
    ) -> str | None:
        """Return AES-256 ciphertext or None when not configured."""

    async def list_credentials(self, user_id: UUID) -> tuple[MarketplaceCredentialView, ...]:
        """List configured platforms without decrypting secrets."""

    async def delete_credentials(self, *, user_id: UUID, platform: MarketplacePlatform) -> bool:
        """Remove stored credentials for a platform."""

    async def get_completed_export_source(
        self, *, user_id: UUID, generation_job_id: UUID
    ) -> ExportCardSource | None:
        """
        Return marketplace text, slide keys, and product_category for a completed job.

        None when the job is missing, not owned, incomplete, or lacks text/images.
        """

    async def save_export(
        self,
        *,
        user_id: UUID,
        platform: MarketplacePlatform,
        generation_job_id: UUID,
        status: ExportStatus,
        vendor_code: str,
        external_task_id: str | None,
        external_offer_id: str | None,
        message: str,
        validation_payload: dict[str, Any],
        request_payload: dict[str, Any],
    ) -> ExportResultView:
        """Persist an export attempt and return the domain view."""


class ImageAssetPort(Protocol):
    """Load generated slide bytes and issue public HTTPS URLs for marketplaces."""

    async def inspect_images(
        self, object_keys: tuple[str, ...]
    ) -> tuple[ImageAssetMeta, ...]:
        """Download and inspect slide images (dimensions, format, size)."""

    async def public_urls(self, object_keys: tuple[str, ...]) -> tuple[str, ...]:
        """Return publicly reachable HTTPS URLs for media upload APIs."""


class MarketplaceSellerPort(Protocol):
    """One marketplace adapter that creates a seller draft / listing."""

    platform: MarketplacePlatform

    async def create_product_draft(
        self,
        *,
        credentials: dict[str, str],
        vendor_code: str,
        title: str,
        description: str,
        characteristics: tuple[str, ...],
        image_urls: tuple[str, ...],
        extras: dict[str, Any],
    ) -> tuple[str | None, str | None, str]:
        """
        Push the card to the marketplace draft/listing pipeline.

        Returns (external_task_id, external_offer_id, human_message).
        """
