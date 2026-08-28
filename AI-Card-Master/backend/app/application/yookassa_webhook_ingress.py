"""Shared YooKassa webhook verification: never trust the notification body."""

from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Protocol


class YooKassaPaymentFindPort(Protocol):
    """Lookup port for YooKassa ``Payment.find`` / ``Payment.find_one``."""

    async def find_payment(self, payment_id: str) -> dict[str, Any]:
        """Re-fetch a payment from YooKassa by id."""


@dataclass(frozen=True, slots=True)
class YooKassaWebhookVerification:
    """Notification fields plus the authoritative upstream payment snapshot."""

    event: str
    payment_id: str
    upstream_status: str
    amount: Decimal | None
    raw_payload: str
    found: dict[str, Any]


class YooKassaWebhookIngress:
    """Re-fetch every notification via ``Payment.find`` before applying billing."""

    def __init__(self, lookup: YooKassaPaymentFindPort) -> None:
        self._lookup = lookup

    async def verify(self, payload: dict[str, Any]) -> YooKassaWebhookVerification:
        event = str(payload.get("event") or "").strip()
        obj = payload.get("object")
        if not isinstance(obj, dict):
            raise ValueError("Webhook payload missing payment object.")

        payment_id = str(obj.get("id") or "").strip()
        if not payment_id:
            raise ValueError("Webhook payment id is missing.")

        found = await self._lookup.find_payment(payment_id)
        amount: Decimal | None = None
        amount_block = found.get("amount") or {}
        if isinstance(amount_block, dict) and amount_block.get("value") is not None:
            try:
                amount = Decimal(str(amount_block.get("value")))
            except (InvalidOperation, ValueError) as exc:
                raise ValueError("Invalid amount in verified YooKassa payment.") from exc

        return YooKassaWebhookVerification(
            event=event,
            payment_id=payment_id,
            upstream_status=str(found.get("status") or "").strip().lower(),
            amount=amount,
            raw_payload=json.dumps(payload, ensure_ascii=False),
            found=found,
        )
