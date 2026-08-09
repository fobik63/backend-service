"""Persistence for user marketplace credentials and publish history."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.credential_crypto import (
    CredentialCryptoError,
    decrypt_credentials,
    decrypt_secret_value,
    encrypt_credentials,
    encrypt_secret_value,
)
from app.domain.marketplace_publish import (
    PublishPlatform,
    PublishResultView,
    PublishStatus,
    UserMarketplaceCredentialsView,
)
from app.models.marketplace_export import MarketplaceCredential, MarketplacePublication
from app.models.user import User
from app.domain.export import MarketplacePlatform


class MarketplacePublishRepository:
    """SQLAlchemy adapter for user credential columns + publication history."""

    def __init__(self, session: AsyncSession, *, encryption_secret: str) -> None:
        if not encryption_secret.strip():
            raise ValueError("Marketplace credential encryption secret is not configured.")
        self._session = session
        self._secret = encryption_secret

    async def get_credentials_view(
        self, user_id: UUID
    ) -> UserMarketplaceCredentialsView:
        user = await self._session.get(User, user_id)
        if user is None:
            return UserMarketplaceCredentialsView(
                wb_configured=False,
                ozon_configured=False,
            )
        return UserMarketplaceCredentialsView(
            wb_configured=bool(user.wb_api_token_ciphertext),
            ozon_configured=bool(
                user.ozon_client_id_ciphertext and user.ozon_api_key_ciphertext
            ),
            updated_at=user.marketplace_credentials_updated_at,
        )

    async def load_decrypted_secrets(
        self, user_id: UUID
    ) -> dict[str, str | None]:
        user = await self._session.get(User, user_id)
        if user is None:
            return {
                "wb_api_token": None,
                "ozon_client_id": None,
                "ozon_api_key": None,
            }
        return {
            "wb_api_token": self._decrypt_optional(user.wb_api_token_ciphertext),
            "ozon_client_id": self._decrypt_optional(user.ozon_client_id_ciphertext),
            "ozon_api_key": self._decrypt_optional(user.ozon_api_key_ciphertext),
        }

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
        user = await self._session.get(User, user_id)
        if user is None:
            raise ValueError(f"User {user_id} not found.")

        now = datetime.now(UTC)
        if clear_wb:
            user.wb_api_token_ciphertext = None
        elif wb_api_token_ciphertext is not None:
            user.wb_api_token_ciphertext = wb_api_token_ciphertext

        if clear_ozon:
            user.ozon_client_id_ciphertext = None
            user.ozon_api_key_ciphertext = None
        else:
            if ozon_client_id_ciphertext is not None:
                user.ozon_client_id_ciphertext = ozon_client_id_ciphertext
            if ozon_api_key_ciphertext is not None:
                user.ozon_api_key_ciphertext = ozon_api_key_ciphertext

        user.marketplace_credentials_updated_at = now
        await self._session.flush()

        # Keep Direct Export credentials mirror in sync for WB / Ozon.
        await self._mirror_to_marketplace_credentials(user)
        await self._session.commit()
        await self._session.refresh(user)

        return UserMarketplaceCredentialsView(
            wb_configured=bool(user.wb_api_token_ciphertext),
            ozon_configured=bool(
                user.ozon_client_id_ciphertext and user.ozon_api_key_ciphertext
            ),
            updated_at=user.marketplace_credentials_updated_at,
        )

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
        request_payload: dict[str, Any],
    ) -> PublishResultView:
        row = MarketplacePublication(
            user_id=user_id,
            platform=platform.value,
            product_id=product_id,
            status=status.value,
            message=message[:1000],
            external_task_id=external_task_id,
            error_logs=list(error_logs),
            request_payload=request_payload,
        )
        self._session.add(row)
        await self._session.commit()
        await self._session.refresh(row)
        return PublishResultView(
            id=row.id,
            platform=platform,
            product_id=row.product_id,
            status=PublishStatus(row.status),
            message=row.message,
            external_task_id=row.external_task_id,
            error_logs=tuple(str(item) for item in (row.error_logs or [])),
            created_at=row.created_at,
        )

    def encrypt_plain_secret(self, value: str) -> str:
        return encrypt_secret_value(value, secret=self._secret)

    def _decrypt_optional(self, ciphertext: str | None) -> str | None:
        if not ciphertext:
            return None
        try:
            return decrypt_secret_value(ciphertext, secret=self._secret)
        except CredentialCryptoError:
            return None

    async def _mirror_to_marketplace_credentials(self, user: User) -> None:
        """Upsert / delete mirrored rows used by Direct Export."""

        wb_token = self._decrypt_optional(user.wb_api_token_ciphertext)
        if wb_token:
            await self._upsert_platform_ciphertext(
                user_id=user.id,
                platform=MarketplacePlatform.WILDBERRIES,
                payload={"api_token": wb_token},
            )
        else:
            await self._delete_platform(user.id, MarketplacePlatform.WILDBERRIES)

        ozon_client = self._decrypt_optional(user.ozon_client_id_ciphertext)
        ozon_key = self._decrypt_optional(user.ozon_api_key_ciphertext)
        if ozon_client and ozon_key:
            await self._upsert_platform_ciphertext(
                user_id=user.id,
                platform=MarketplacePlatform.OZON,
                payload={"client_id": ozon_client, "api_key": ozon_key},
            )
        else:
            await self._delete_platform(user.id, MarketplacePlatform.OZON)

    async def _upsert_platform_ciphertext(
        self,
        *,
        user_id: UUID,
        platform: MarketplacePlatform,
        payload: dict[str, str],
    ) -> None:
        from sqlalchemy import select

        ciphertext = encrypt_credentials(payload, secret=self._secret)
        row = await self._session.scalar(
            select(MarketplaceCredential).where(
                MarketplaceCredential.user_id == user_id,
                MarketplaceCredential.platform == platform.value,
            )
        )
        now = datetime.now(UTC)
        if row is None:
            self._session.add(
                MarketplaceCredential(
                    user_id=user_id,
                    platform=platform.value,
                    ciphertext=ciphertext,
                    label="user-credentials",
                )
            )
        else:
            row.ciphertext = ciphertext
            row.updated_at = now

    async def _delete_platform(
        self, user_id: UUID, platform: MarketplacePlatform
    ) -> None:
        from sqlalchemy import delete

        await self._session.execute(
            delete(MarketplaceCredential).where(
                MarketplaceCredential.user_id == user_id,
                MarketplaceCredential.platform == platform.value,
            )
        )
