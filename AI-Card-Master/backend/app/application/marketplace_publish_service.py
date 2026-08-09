"""Use cases: store seller credentials and publish media/SEO to WB / Ozon."""

from __future__ import annotations

import logging
from typing import Any, Protocol
from uuid import UUID

from app.application.ports.marketplace_publish import (
    MarketplacePublishClientPort,
    PublishHistoryPort,
    UserCredentialsPersistencePort,
)
from app.core.credential_crypto import CredentialCryptoError, encrypt_secret_value
from app.domain.marketplace_publish import (
    MarketplacePublishError,
    MarketplacePublishNotFoundError,
    MarketplacePublishUpstreamError,
    MarketplacePublishValidationError,
    OzonPublishRequest,
    PublishPlatform,
    PublishResultView,
    PublishStatus,
    SellerProductView,
    UserMarketplaceCredentialsInput,
    UserMarketplaceCredentialsView,
    WbPublishRequest,
)

logger = logging.getLogger(__name__)


class _CredentialsStore(UserCredentialsPersistencePort, Protocol):
    """Persistence port plus optional encrypt helper used by the use-case."""

    def encrypt_plain_secret(self, value: str) -> str: ...


class MarketplacePublishService:
    """Encrypt credentials on the user row and push assets into seller cabinets."""

    def __init__(
        self,
        repository: _CredentialsStore,
        *,
        clients: dict[PublishPlatform, MarketplacePublishClientPort],
        history: PublishHistoryPort | None = None,
        encryption_secret: str | None = None,
    ) -> None:
        self._repository = repository
        self._clients = clients
        self._history: PublishHistoryPort = history or repository  # type: ignore[assignment]
        self._encryption_secret = encryption_secret

    def _encrypt(self, value: str) -> str:
        encrypt = getattr(self._repository, "encrypt_plain_secret", None)
        if callable(encrypt):
            return encrypt(value)
        if not self._encryption_secret:
            raise MarketplacePublishValidationError(
                "Marketplace credential encryption secret is not configured."
            )
        return encrypt_secret_value(value, secret=self._encryption_secret)

    async def get_credentials(self, user_id: UUID) -> UserMarketplaceCredentialsView:
        return await self._repository.get_credentials_view(user_id)

    async def save_credentials(
        self,
        *,
        user_id: UUID,
        payload: UserMarketplaceCredentialsInput,
    ) -> UserMarketplaceCredentialsView:
        """Encrypt and store credentials; optionally validate against seller APIs."""

        existing = await self._repository.load_decrypted_secrets(user_id)
        wb_cipher: str | None = None
        ozon_client_cipher: str | None = None
        ozon_key_cipher: str | None = None

        if payload.wb_api_token is not None:
            wb_cipher = self._encrypt(payload.wb_api_token)

        next_ozon_client = (
            payload.ozon_client_id
            if payload.ozon_client_id is not None
            else existing.get("ozon_client_id")
        )
        next_ozon_key = (
            payload.ozon_api_key
            if payload.ozon_api_key is not None
            else existing.get("ozon_api_key")
        )
        if payload.ozon_client_id is not None or payload.ozon_api_key is not None:
            if not next_ozon_client or not next_ozon_key:
                raise MarketplacePublishValidationError(
                    "Ozon requires both ozon_client_id and ozon_api_key."
                )
            ozon_client_cipher = self._encrypt(next_ozon_client)
            ozon_key_cipher = self._encrypt(next_ozon_key)

        try:
            view = await self._repository.save_encrypted_secrets(
                user_id=user_id,
                wb_api_token_ciphertext=wb_cipher,
                ozon_client_id_ciphertext=ozon_client_cipher,
                ozon_api_key_ciphertext=ozon_key_cipher,
            )
        except CredentialCryptoError as exc:
            raise MarketplacePublishValidationError(str(exc)) from exc
        except ValueError as exc:
            raise MarketplacePublishNotFoundError(str(exc)) from exc

        if not payload.validate_credentials:
            return view

        secrets = await self._repository.load_decrypted_secrets(user_id)
        wb_valid: bool | None = None
        ozon_valid: bool | None = None
        wb_message: str | None = None
        ozon_message: str | None = None

        if secrets.get("wb_api_token") and (
            payload.wb_api_token is not None or view.wb_configured
        ):
            wb_result = await self._clients[PublishPlatform.WILDBERRIES].validate_credentials(
                {"api_token": secrets["wb_api_token"] or ""}
            )
            wb_valid = wb_result.is_valid
            wb_message = wb_result.message

        if secrets.get("ozon_client_id") and secrets.get("ozon_api_key") and (
            payload.ozon_client_id is not None
            or payload.ozon_api_key is not None
            or view.ozon_configured
        ):
            ozon_result = await self._clients[PublishPlatform.OZON].validate_credentials(
                {
                    "client_id": secrets["ozon_client_id"] or "",
                    "api_key": secrets["ozon_api_key"] or "",
                }
            )
            ozon_valid = ozon_result.is_valid
            ozon_message = ozon_result.message

        return UserMarketplaceCredentialsView(
            wb_configured=view.wb_configured,
            ozon_configured=view.ozon_configured,
            wb_valid=wb_valid,
            ozon_valid=ozon_valid,
            wb_validation_message=wb_message,
            ozon_validation_message=ozon_message,
            updated_at=view.updated_at,
        )

    async def delete_credentials(
        self,
        *,
        user_id: UUID,
        clear_wb: bool = False,
        clear_ozon: bool = False,
    ) -> UserMarketplaceCredentialsView:
        if not clear_wb and not clear_ozon:
            raise MarketplacePublishValidationError(
                "Specify clear_wb and/or clear_ozon to delete credentials."
            )
        try:
            return await self._repository.save_encrypted_secrets(
                user_id=user_id,
                clear_wb=clear_wb,
                clear_ozon=clear_ozon,
            )
        except ValueError as exc:
            raise MarketplacePublishNotFoundError(str(exc)) from exc

    async def validate_stored_credentials(
        self, user_id: UUID
    ) -> UserMarketplaceCredentialsView:
        view = await self._repository.get_credentials_view(user_id)
        secrets = await self._repository.load_decrypted_secrets(user_id)
        wb_valid: bool | None = None
        ozon_valid: bool | None = None
        wb_message: str | None = None
        ozon_message: str | None = None

        if secrets.get("wb_api_token"):
            result = await self._clients[PublishPlatform.WILDBERRIES].validate_credentials(
                {"api_token": secrets["wb_api_token"] or ""}
            )
            wb_valid = result.is_valid
            wb_message = result.message
        if secrets.get("ozon_client_id") and secrets.get("ozon_api_key"):
            result = await self._clients[PublishPlatform.OZON].validate_credentials(
                {
                    "client_id": secrets["ozon_client_id"] or "",
                    "api_key": secrets["ozon_api_key"] or "",
                }
            )
            ozon_valid = result.is_valid
            ozon_message = result.message

        return UserMarketplaceCredentialsView(
            wb_configured=view.wb_configured,
            ozon_configured=view.ozon_configured,
            wb_valid=wb_valid,
            ozon_valid=ozon_valid,
            wb_validation_message=wb_message,
            ozon_validation_message=ozon_message,
            updated_at=view.updated_at,
        )

    async def publish_wb(
        self, *, user_id: UUID, request: WbPublishRequest
    ) -> PublishResultView:
        return await self._publish(
            user_id=user_id,
            platform=PublishPlatform.WILDBERRIES,
            request=request,
            product_id=str(request.nm_id),
            request_payload=request.model_dump(mode="json"),
        )

    async def publish_ozon(
        self, *, user_id: UUID, request: OzonPublishRequest
    ) -> PublishResultView:
        return await self._publish(
            user_id=user_id,
            platform=PublishPlatform.OZON,
            request=request,
            product_id=str(request.product_id),
            request_payload=request.model_dump(mode="json"),
        )

    async def list_seller_products(
        self,
        *,
        user_id: UUID,
        platform: PublishPlatform,
        limit: int = 50,
    ) -> tuple[SellerProductView, ...]:
        """List cabinet products for the authenticated seller credentials."""

        if limit < 1 or limit > 100:
            raise MarketplacePublishValidationError("limit must be between 1 and 100.")
        credentials = await self._credentials_for_platform(user_id, platform)
        client = self._clients[platform]
        return await client.list_products(credentials=credentials, limit=limit)

    async def _publish(
        self,
        *,
        user_id: UUID,
        platform: PublishPlatform,
        request: WbPublishRequest | OzonPublishRequest,
        product_id: str,
        request_payload: dict[str, Any],
    ) -> PublishResultView:
        credentials = await self._credentials_for_platform(user_id, platform)
        client = self._clients[platform]
        try:
            result = await client.publish(credentials=credentials, request=request)
        except MarketplacePublishUpstreamError as exc:
            return await self._history.save_publication(
                user_id=user_id,
                platform=platform,
                product_id=product_id,
                status=PublishStatus.FAILED,
                message=str(exc),
                external_task_id=None,
                error_logs=exc.error_logs,
                request_payload=request_payload,
            )
        except MarketplacePublishError as exc:
            return await self._history.save_publication(
                user_id=user_id,
                platform=platform,
                product_id=product_id,
                status=PublishStatus.FAILED,
                message=str(exc),
                external_task_id=None,
                error_logs=(str(exc),),
                request_payload=request_payload,
            )

        return await self._history.save_publication(
            user_id=user_id,
            platform=platform,
            product_id=product_id,
            status=result.status,
            message=result.message,
            external_task_id=result.external_task_id,
            error_logs=result.error_logs,
            request_payload=request_payload,
        )

    async def _credentials_for_platform(
        self, user_id: UUID, platform: PublishPlatform
    ) -> dict[str, str]:
        secrets = await self._repository.load_decrypted_secrets(user_id)
        if platform is PublishPlatform.WILDBERRIES:
            token = secrets.get("wb_api_token")
            if not token:
                raise MarketplacePublishNotFoundError(
                    "Connect Wildberries API token via /api/user/credentials first."
                )
            return {"api_token": token, "wb_api_token": token}
        client_id = secrets.get("ozon_client_id")
        api_key = secrets.get("ozon_api_key")
        if not client_id or not api_key:
            raise MarketplacePublishNotFoundError(
                "Connect Ozon Client-Id and Api-Key via /api/user/credentials first."
            )
        return {
            "client_id": client_id,
            "api_key": api_key,
            "ozon_client_id": client_id,
            "ozon_api_key": api_key,
        }
