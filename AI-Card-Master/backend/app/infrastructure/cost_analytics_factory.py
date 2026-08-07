"""Composition root for AI Cost Dashboard (plan §80)."""

from __future__ import annotations

from functools import lru_cache

from sqlalchemy.ext.asyncio import AsyncSession

from app.application.cost_analytics_service import CostAnalyticsService
from app.core.config import Settings, get_settings
from app.domain.cost_analytics import CostAlertPolicy
from app.infrastructure.persistence.cost_analytics_repository import (
    CostAnalyticsRepository,
    FailOpenCostAnalyticsRepository,
)
from app.services.telegram_alerts import send_operator_telegram


class TelegramCostAlertNotifier:
    """``CostAlertNotifierPort`` over operator Telegram."""

    async def notify(self, message: str) -> None:
        await send_operator_telegram(message)


class NoopCostAlertNotifier:
    async def notify(self, message: str) -> None:
        return None


def build_cost_alert_policy(settings: Settings | None = None) -> CostAlertPolicy:
    cfg = settings or get_settings()
    return CostAlertPolicy(
        daily_limit_usd=cfg.cost_daily_limit_usd,
        generation_spike_ratio=cfg.cost_generation_spike_ratio,
        latency_spike_ratio=cfg.cost_latency_spike_ratio,
        latency_warn_ms=cfg.cost_latency_warn_ms,
        alerts_enabled=cfg.cost_alerts_enabled,
    )


def build_cost_analytics_service(
    session: AsyncSession,
    *,
    settings: Settings | None = None,
    fail_open: bool = False,
) -> CostAnalyticsService:
    """Build a request-scoped cost analytics service bound to ``session``."""

    cfg = settings or get_settings()
    repo = CostAnalyticsRepository(session)
    if fail_open:
        repo = FailOpenCostAnalyticsRepository(repo)  # type: ignore[assignment]
    sale = cfg.cost_generation_sale_price_usd
    sale_price = sale if sale is not None and sale > 0 else None
    notifier: TelegramCostAlertNotifier | NoopCostAlertNotifier
    if cfg.cost_alerts_enabled:
        notifier = TelegramCostAlertNotifier()
    else:
        notifier = NoopCostAlertNotifier()
    return CostAnalyticsService(
        repository=repo,
        alert_notifier=notifier,
        alert_policy=build_cost_alert_policy(cfg),
        generation_sale_price_usd=sale_price,
        alert_cooldown_seconds=cfg.cost_alert_cooldown_seconds,
    )


@lru_cache(maxsize=1)
def _cached_alert_policy() -> CostAlertPolicy:
    return build_cost_alert_policy()
