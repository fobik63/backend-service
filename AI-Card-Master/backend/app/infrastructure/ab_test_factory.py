"""Composition root for Automated A/B Testing Logic."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.application.ab_test_service import AbTestCredentialsError, AbTestService
from app.core.config import get_settings
from app.core.credential_crypto import CredentialCryptoError, decrypt_credentials
from app.domain.ab_test import AbTestConfig
from app.domain.export import MarketplacePlatform
from app.infrastructure.claude.client import (
    Claude47VisionClient,
    ClaudeConfigurationError,
)
from app.infrastructure.marketplaces.ads_clients import build_marketplace_ads_client
from app.infrastructure.persistence.ab_test_repository import AbTestRepository
from app.infrastructure.persistence.export_repository import ExportRepository


class ExportAdsCredentialsAdapter:
    """Load decrypted seller credentials for ads cabinet calls."""

    def __init__(self, db_session: AsyncSession, *, encryption_secret: str) -> None:
        self._exports = ExportRepository(db_session)
        self._encryption_secret = encryption_secret

    async def get_ads_credentials(
        self, *, user_id: UUID, platform: str
    ) -> dict[str, str]:
        try:
            export_platform = MarketplacePlatform(platform.strip().lower())
        except ValueError as exc:
            # Accept wb alias.
            normalized = platform.strip().lower()
            if normalized == "wb":
                export_platform = MarketplacePlatform.WILDBERRIES
            else:
                raise AbTestCredentialsError(
                    f"Unsupported marketplace platform: {platform!r}"
                ) from exc

        ciphertext = await self._exports.get_credentials_ciphertext(
            user_id=user_id,
            platform=export_platform,
        )
        if ciphertext is None:
            raise AbTestCredentialsError(
                f"No stored credentials for platform={export_platform.value}."
            )
        try:
            return decrypt_credentials(ciphertext, secret=self._encryption_secret)
        except CredentialCryptoError as exc:
            raise AbTestCredentialsError(str(exc)) from exc


def build_ab_test_service(
    db_session: AsyncSession,
    *,
    require_claude_client: bool = False,
    hypothesis_generator: Claude47VisionClient | None = None,
) -> AbTestService:
    """Wire ports for HTTP handlers and Celery workers."""

    settings = get_settings()
    client = hypothesis_generator
    if client is None and require_claude_client:
        client = Claude47VisionClient(settings)
    elif client is None:
        try:
            if (
                settings.claude_47_api_key
                and settings.claude_47_api_key.get_secret_value().strip()
            ):
                client = Claude47VisionClient(settings)
        except ClaudeConfigurationError:
            client = None

    secret = settings.marketplace_credentials_secret.get_secret_value().strip()
    if not secret:
        secret = settings.jwt_secret_key.get_secret_value()

    config = AbTestConfig(
        duration_days=settings.ab_test_duration_days,
        variant_count=3,
        min_impressions_for_decision=settings.ab_test_min_impressions,
        min_ctr_gap_pct=settings.ab_test_min_ctr_gap_pct,
        auto_delete_losers=settings.ab_test_auto_delete_losers,
        auto_promote_winner=settings.ab_test_auto_promote_winner,
    )

    def ads_factory(marketplace: str):
        return build_marketplace_ads_client(
            marketplace,
            wb_base_url=settings.wildberries_advert_api_base_url,
            ozon_base_url=settings.ozon_performance_api_base_url,
            timeout_seconds=settings.ab_test_ads_timeout_seconds,
            allow_local_fallback=settings.ab_test_allow_ads_fallback,
        )

    return AbTestService(
        AbTestRepository(db_session),
        model_name=settings.claude_47_model,
        redis_stage_ttl_seconds=settings.claude_47_stage_cache_ttl_seconds,
        default_config=config,
        hypothesis_generator=client,
        ads_client_factory=ads_factory,
        credentials=ExportAdsCredentialsAdapter(
            db_session,
            encryption_secret=secret,
        ),
        allow_ads_fallback=settings.ab_test_allow_ads_fallback,
    )
