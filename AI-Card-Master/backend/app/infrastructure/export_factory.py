"""Composition root for Direct Export + Fail-Safe sandbox (plan §59)."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.application.export_service import ExportService
from app.core.config import Settings, get_settings
from app.domain.export import MarketplacePlatform
from app.domain.smart_reasoning import ReasoningTaskKind
from app.infrastructure.claude_client_loader import load_claude_client
from app.infrastructure.marketplaces.amazon_client import AmazonSellerClient
from app.infrastructure.marketplaces.image_assets import S3ImageAssetAdapter
from app.infrastructure.marketplaces.ozon_client import OzonSellerClient
from app.infrastructure.marketplaces.wildberries_client import WildberriesSellerClient
from app.infrastructure.persistence.export_repository import ExportRepository
from app.infrastructure.smart_reasoning_factory import (
    build_analytics_cache,
    resolve_claude_model,
)


def build_export_service(
    db_session: AsyncSession,
    *,
    settings: Settings | None = None,
    require_claude_client: bool = False,
) -> ExportService:
    """Wire Direct Export + optional Claude Fail-Safe auto-fix."""

    cfg = settings or get_settings()
    secret = cfg.marketplace_credentials_secret.get_secret_value()
    if not secret.strip():
        secret = cfg.jwt_secret_key.get_secret_value()

    fix_suggester = None
    if cfg.fail_safe_export_enabled and cfg.fail_safe_export_claude_fix_enabled:
        fix_suggester = _build_claude_fix_suggester(
            cfg, require_claude_client=require_claude_client
        )

    return ExportService(
        ExportRepository(db_session),
        S3ImageAssetAdapter(),
        {
            MarketplacePlatform.WILDBERRIES: WildberriesSellerClient(
                base_url=cfg.wildberries_content_api_base_url,
                timeout_seconds=cfg.marketplace_export_timeout_seconds,
            ),
            MarketplacePlatform.OZON: OzonSellerClient(
                base_url=cfg.ozon_seller_api_base_url,
                timeout_seconds=cfg.marketplace_export_timeout_seconds,
            ),
            MarketplacePlatform.AMAZON: AmazonSellerClient(
                sp_api_base_url=cfg.amazon_sp_api_base_url,
                timeout_seconds=cfg.marketplace_export_timeout_seconds,
            ),
        },
        fernet_secret=secret,
        fix_suggester=fix_suggester,
        fail_safe_enabled=cfg.fail_safe_export_enabled,
        claude_fix_enabled=cfg.fail_safe_export_claude_fix_enabled,
    )


def _build_claude_fix_suggester(
    settings: Any,
    *,
    require_claude_client: bool,
) -> Any | None:
    from app.infrastructure.claude.facades import wrap_claude_for_domain

    task = ReasoningTaskKind.EXPORT_FAIL_SAFE_FIX
    client = load_claude_client(
        settings,
        require=require_claude_client,
        model_name=resolve_claude_model(task, settings),
        analytics_cache=build_analytics_cache(),
        analytics_cache_ttl_seconds=settings.claude_analytics_cache_ttl_seconds,
        analytics_task_kind=task.value,
    )
    return wrap_claude_for_domain(client, domain="export_fix")
