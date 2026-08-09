"""Ports for marketplace publish: user credentials, seller APIs, history."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol
from uuid import UUID

from app.domain.marketplace_publish import (
    CredentialValidationResult,
    OzonPublishRequest,
    PublishPlatform,
    PublishResultView,
    PublishStatus,
    SellerProductView,
    UserMarketplaceCredentialsView,
    WbPublishRequest,
)


class UserCredentialsPersistencePort(Protocol):
    """Encrypted WB / Ozon seller secrets stored on the user row."""

    async def get_credentials_view(
        self, user_id: UUID
    ) -> UserMarketplaceCredentialsView:
        """Return configuration flags without decrypting secrets."""

    async def load_decrypted_secrets(
        self, user_id: UUID
    ) -> dict[str, str | None]:
        """
        Return decrypted secrets keyed by field name.

        Keys: wb_api_token, ozon_client_id, ozon_api_key (values may be None).
        """

    async def save_encrypted_secrets(
        self,
        *,
        user_id: UUID,
        wb_api_token_ciphertext: str | None = None,
        ozon_client_id_ciphertext: str | None = None,
        ozon_api_key_ciphertext: str | None = None,
        clear_wb: bool = False,
        clear_ozon: bool = False,
    ) -> UserMarketplaceCredentialsView:
        """Persist ciphertext columns; None args leave existing values untouched."""


class PublishHistoryPort(Protocol):
    """Persist publish attempts with status and marketplace error logs."""

    async def save_publication(
        self,
        *,
        user_id: UUID,
        platform: PublishPlatform,
        product_id: str,
        status: PublishStatus,
        message: str,
        external_task_id: str | None,
        error_logs: tuple[str, ...],
        request_payload: dict,
    ) -> PublishResultView:
        """Insert a publication row and return the domain view."""


class MarketplacePublishClientPort(Protocol):
    """Seller API adapter that validates credentials and updates an existing product."""

    platform: PublishPlatform

    async def validate_credentials(
        self, credentials: dict[str, str]
    ) -> CredentialValidationResult:
        """Probe the marketplace with the given credentials."""

    async def publish(
        self,
        *,
        credentials: dict[str, str],
        request: WbPublishRequest | OzonPublishRequest,
    ) -> PublishResultView:
        """
        Push images and description to an existing card/product.

        The returned view may omit ``id`` / ``created_at``; the service persists them.
        """

    async def list_products(
        self,
        *,
        credentials: dict[str, str],
        limit: int = 50,
    ) -> tuple[SellerProductView, ...]:
        """Return recent seller products for the publish target picker."""
