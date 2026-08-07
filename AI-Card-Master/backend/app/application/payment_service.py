"""Application façade for payments / balance / daily bonus (audit A2).

API routers depend on this service instead of assembling BillingService,
WinbackService, and YooKassa adapters inline.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from app.application.winback_service import WinbackService
from app.models.enums import TariffCode
from app.models.payment import Payment
from app.models.user import User
from app.services.billing_service import (
    BillingResult,
    BillingService,
    DailyBonusResult,
    describe_tariff,
)
from app.services.tariffs import get_tariff_plan, list_tariff_plans
from app.services.yookassa_service import YooKassaService

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class BalanceSnapshot:
    ai_coins: int
    daily_bonus_available: bool
    daily_bonus_streak: int
    daily_bonus_coins: int
    last_daily_bonus_claimed_at: datetime | None
    next_daily_bonus_available_at: datetime


@dataclass(frozen=True, slots=True)
class CheckoutResult:
    payment: Payment


@dataclass(frozen=True, slots=True)
class WebhookProcessResult:
    detail: str
    already_processed: bool = False


class PaymentApplicationService:
    """Orchestrates tariff catalog, checkout, webhooks, and daily bonus."""

    def __init__(
        self,
        *,
        billing: BillingService,
        yookassa: YooKassaService | None,
        winback: WinbackService,
        daily_bonus_coins: int,
    ) -> None:
        self._billing = billing
        self._yookassa = yookassa
        self._winback = winback
        self._daily_bonus_coins = daily_bonus_coins

    def _require_yookassa(self) -> YooKassaService:
        if self._yookassa is None:
            from app.services.yookassa_service import YooKassaConfigurationError

            raise YooKassaConfigurationError(
                "YooKassa is not configured for this environment."
            )
        return self._yookassa

    def list_tariffs(self) -> list[dict[str, object]]:
        return [describe_tariff(plan) for plan in list_tariff_plans()]

    def balance_snapshot(self, user: User) -> BalanceSnapshot:
        now = datetime.now(UTC)
        last_claimed_at = user.daily_bonus_claimed_at
        if last_claimed_at is not None and last_claimed_at.tzinfo is None:
            last_claimed_at = last_claimed_at.replace(tzinfo=UTC)
        daily_bonus_available = (
            last_claimed_at is None
            or last_claimed_at.astimezone(UTC).date() < now.date()
        )
        next_available_at = datetime(
            now.year, now.month, now.day, tzinfo=UTC
        ) + timedelta(days=1)
        return BalanceSnapshot(
            ai_coins=user.ai_coins,
            daily_bonus_available=daily_bonus_available,
            daily_bonus_streak=user.daily_bonus_streak,
            daily_bonus_coins=self._daily_bonus_coins,
            last_daily_bonus_claimed_at=last_claimed_at,
            next_daily_bonus_available_at=next_available_at,
        )

    async def claim_daily_bonus(self, user_id: UUID) -> DailyBonusResult:
        return await self._billing.claim_daily_bonus(user_id)

    async def create_checkout(
        self,
        *,
        user: User,
        tariff_code: TariffCode,
    ) -> CheckoutResult:
        plan = get_tariff_plan(tariff_code)
        amount_rub, discount_percent, _offer_id = (
            await self._winback.resolve_checkout_amount(
                user_id=user.id,
                catalog_price_rub=plan.price_rub,
            )
        )
        yookassa = self._require_yookassa()
        created = await yookassa.create_tariff_payment(
            user_id=str(user.id),
            tariff_code=tariff_code,
            customer_email=user.email,
            amount_rub_override=amount_rub if discount_percent is not None else None,
            discount_percent=discount_percent,
        )
        payment = await self._billing.create_pending_payment(
            user_id=user.id,
            tariff_code=tariff_code,
            yookassa_payment_id=created.payment_id,
            amount_rub=created.amount_rub,
            confirmation_url=created.confirmation_url,
            description=created.description or None,
            currency=created.currency,
            discount_percent=discount_percent,
        )
        return CheckoutResult(payment=payment)

    async def process_yookassa_webhook(
        self, payload: dict[str, Any]
    ) -> WebhookProcessResult:
        event = str(payload.get("event") or "").strip()
        obj = payload.get("object")
        if not isinstance(obj, dict):
            raise ValueError("Webhook payload missing payment object.")

        yookassa_payment_id = str(obj.get("id") or "").strip()
        if not yookassa_payment_id:
            raise ValueError("Webhook payment id is missing.")

        raw_payload = json.dumps(payload, ensure_ascii=False)

        if event == "payment.canceled":
            await self._billing.mark_payment_canceled(
                yookassa_payment_id=yookassa_payment_id,
                raw_payload=raw_payload,
            )
            return WebhookProcessResult(detail="Payment marked as canceled.")

        if event != "payment.succeeded":
            return WebhookProcessResult(
                detail=f"Ignored event '{event or 'unknown'}'."
            )

        yookassa = self._require_yookassa()
        verified = await yookassa.get_payment(yookassa_payment_id)
        if str(verified.get("status") or "").lower() != "succeeded":
            return WebhookProcessResult(
                detail=(
                    f"Upstream payment status is '{verified.get('status')}', "
                    "billing was not applied."
                )
            )

        amount_block = verified.get("amount") or {}
        expected_amount = Decimal(str(amount_block.get("value")))

        result: BillingResult = await self._billing.apply_successful_payment(
            yookassa_payment_id=yookassa_payment_id,
            expected_amount=expected_amount,
            raw_payload=raw_payload,
        )

        if not result.already_processed:
            payment = await self._billing.get_payment_by_yookassa_id(
                yookassa_payment_id
            )
            catalog_price = get_tariff_plan(result.tariff_code).price_rub
            if payment is not None and payment.amount_rub != catalog_price:
                _amount, _percent, offer_id = (
                    await self._winback.resolve_checkout_amount(
                        user_id=result.user_id,
                        catalog_price_rub=catalog_price,
                    )
                )
                await self._winback.redeem_discount_after_payment(
                    user_id=result.user_id,
                    offer_id=offer_id,
                )

        detail = (
            "Payment already processed."
            if result.already_processed
            else (
                f"Tariff '{result.tariff_code.value}' applied; "
                f"+{result.coins_credited} AI-coins; balance={result.new_balance}."
            )
        )
        return WebhookProcessResult(
            detail=detail,
            already_processed=result.already_processed,
        )
