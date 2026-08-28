"""Application service: AI-coin checkout and YooKassa webhook fulfillment."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.ports.yookassa_payments import YooKassaCoinPaymentPort
from app.application.yookassa_webhook_ingress import YooKassaWebhookIngress
from app.core.config import get_settings
from app.domain.coin_pricing import (
    CoinPricingError,
    CoinPurchaseQuote,
    quote_coin_purchase,
)
from app.models.coin_purchase import CoinPurchase
from app.models.enums import PaymentStatus
from app.models.user import User
from app.services.billing_service import (
    BillingNotFoundError,
    BillingService,
    BillingValidationError,
)
from app.services.yookassa_service import YooKassaConfigurationError

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class CoinCheckoutResult:
    purchase: CoinPurchase
    quote: CoinPurchaseQuote
    idempotency_key: str


@dataclass(frozen=True, slots=True)
class CoinWebhookResult:
    detail: str
    already_processed: bool = False
    coins_credited: int = 0


class CoinBillingService:
    """Create YooKassa coin payments and credit balances on succeeded webhooks."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        yookassa: YooKassaCoinPaymentPort | None,
        billing: BillingService | None = None,
    ) -> None:
        self._session = session
        self._yookassa = yookassa
        self._billing = billing or BillingService(session)

    def _require_yookassa(self) -> YooKassaCoinPaymentPort:
        if self._yookassa is None:
            raise YooKassaConfigurationError(
                "YooKassa is not configured for this environment."
            )
        return self._yookassa

    async def create_checkout(
        self,
        *,
        user: User,
        amount_coins: int,
    ) -> CoinCheckoutResult:
        try:
            quote = quote_coin_purchase(amount_coins)
        except CoinPricingError as exc:
            raise BillingValidationError(str(exc)) from exc

        yookassa = self._require_yookassa()
        idempotency_key = str(uuid4())
        settings = get_settings()
        created = await yookassa.create_coin_payment(
            quote=quote,
            user_id=user.id,
            customer_email=user.email,
            idempotency_key=idempotency_key,
            return_url=settings.yookassa_return_url,
        )

        purchase = CoinPurchase(
            user_id=user.id,
            amount_coins=quote.amount_coins,
            unit_price_rub=quote.unit_price_rub,
            amount_rub=created.amount_rub,
            currency=created.currency,
            package_code=quote.package_code,
            yookassa_payment_id=created.payment_id,
            idempotency_key=idempotency_key,
            status=PaymentStatus.PENDING,
            confirmation_url=created.confirmation_url,
            description=created.description or quote.description,
            receipt_description=quote.receipt_item_description,
        )
        self._session.add(purchase)
        await self._session.commit()
        await self._session.refresh(purchase)
        return CoinCheckoutResult(
            purchase=purchase,
            quote=quote,
            idempotency_key=idempotency_key,
        )

    async def process_yookassa_webhook(
        self, payload: dict[str, Any]
    ) -> CoinWebhookResult:
        yookassa = self._require_yookassa()
        verified = await YooKassaWebhookIngress(yookassa).verify(payload)

        if verified.event == "payment.canceled":
            if verified.upstream_status != "canceled":
                return CoinWebhookResult(
                    detail=(
                        f"Upstream payment status is '{verified.found.get('status')}', "
                        "cancel was not applied."
                    )
                )
            await self._mark_canceled(verified.payment_id, verified.raw_payload)
            return CoinWebhookResult(detail="Payment marked as canceled.")

        if verified.event != "payment.succeeded":
            return CoinWebhookResult(
                detail=f"Ignored event '{verified.event or 'unknown'}'."
            )

        if verified.upstream_status != "succeeded":
            return CoinWebhookResult(
                detail=(
                    f"Upstream payment status is '{verified.found.get('status')}', "
                    "billing was not applied."
                )
            )
        if verified.amount is None:
            raise ValueError("Verified YooKassa payment is missing amount.")

        return await self._credit_succeeded_payment(
            yookassa_payment_id=verified.payment_id,
            expected_amount=verified.amount,
            raw_payload=verified.raw_payload,
        )

    async def _mark_canceled(self, yookassa_payment_id: str, raw_payload: str) -> None:
        purchase = await self._lock_purchase(yookassa_payment_id)
        if purchase is None:
            raise BillingNotFoundError(
                f"Coin purchase {yookassa_payment_id} not found in local database."
            )
        if purchase.status == PaymentStatus.SUCCEEDED:
            logger.warning(
                "Skip cancel for already succeeded coin purchase %s",
                yookassa_payment_id,
            )
            return
        purchase.status = PaymentStatus.CANCELED
        purchase.raw_webhook_payload = raw_payload
        purchase.processed_at = datetime.now(UTC)
        await self._session.commit()

    async def _lock_purchase(self, yookassa_payment_id: str) -> CoinPurchase | None:
        result = await self._session.execute(
            select(CoinPurchase)
            .where(CoinPurchase.yookassa_payment_id == yookassa_payment_id)
            .with_for_update()
        )
        return result.scalar_one_or_none()

    async def _credit_succeeded_payment(
        self,
        *,
        yookassa_payment_id: str,
        expected_amount: Decimal,
        raw_payload: str,
    ) -> CoinWebhookResult:
        purchase = await self._lock_purchase(yookassa_payment_id)
        if purchase is None:
            raise BillingNotFoundError(
                f"Coin purchase {yookassa_payment_id} not found in local database."
            )

        if purchase.status == PaymentStatus.SUCCEEDED:
            return CoinWebhookResult(
                detail="Payment already processed.",
                already_processed=True,
                coins_credited=0,
            )

        if purchase.amount_rub != expected_amount:
            raise BillingValidationError(
                "Verified YooKassa amount does not match the local purchase."
            )

        await self._billing.credit_coins_in_transaction(
            user_id=purchase.user_id,
            amount=purchase.amount_coins,
            idempotency_key=f"coin-purchase:{yookassa_payment_id}",
        )
        purchase.status = PaymentStatus.SUCCEEDED
        purchase.raw_webhook_payload = raw_payload
        purchase.processed_at = datetime.now(UTC)
        await self._session.commit()

        logger.info(
            "Credited %s AI-coins for user %s (yookassa_payment_id=%s)",
            purchase.amount_coins,
            purchase.user_id,
            yookassa_payment_id,
        )
        return CoinWebhookResult(
            detail="Coins credited.",
            already_processed=False,
            coins_credited=purchase.amount_coins,
        )
