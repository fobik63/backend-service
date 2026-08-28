"""Port for YooKassa Payments API used by coin billing."""

from __future__ import annotations

from typing import Any, Protocol
from uuid import UUID

from app.domain.coin_pricing import CoinPurchaseQuote
from app.services.yookassa_service import YooKassaPaymentCreated


class YooKassaCoinPaymentPort(Protocol):
    """Create redirect payments and re-fetch them for webhook verification."""

    async def create_coin_payment(
        self,
        *,
        quote: CoinPurchaseQuote,
        user_id: UUID,
        customer_email: str | None,
        idempotency_key: str,
        return_url: str,
    ) -> YooKassaPaymentCreated:
        """Call YooKassa ``Payment.create`` with confirmation.type=redirect."""

    async def find_payment(self, payment_id: str) -> dict[str, Any]:
        """Call YooKassa ``Payment.find_one`` (SDK equivalent of Payment.find)."""
