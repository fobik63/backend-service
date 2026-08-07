"""Composition root for payment / billing HTTP façade."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.application.payment_service import PaymentApplicationService
from app.application.winback_service import WinbackService
from app.core.config import get_settings
from app.infrastructure.persistence.winback_repository import WinbackRepository
from app.services.billing_service import BillingService
from app.services.telegram_user_notify import TelegramUserNotifier
from app.services.yookassa_service import YooKassaService


def build_payment_application_service(
    session: AsyncSession,
    *,
    yookassa: YooKassaService | None = None,
) -> PaymentApplicationService:
    settings = get_settings()
    winback = WinbackService(
        WinbackRepository(session),
        inactivity_days=settings.winback_inactivity_days,
        free_generations=settings.winback_free_generations,
        discount_percent=settings.winback_discount_percent,
        offer_ttl_hours=settings.winback_offer_ttl_hours,
        telegram=TelegramUserNotifier(),
    )
    return PaymentApplicationService(
        billing=BillingService(session),
        yookassa=yookassa,
        winback=winback,
        daily_bonus_coins=settings.daily_bonus_coins,
    )
