"""Async YooKassa API client (payments create + retrieve for webhook verify).

Uses HTTP Basic auth (shopId:secretKey) against api.yookassa.ru/v3.
Official SDK is synchronous; this client stays async via httpx.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import httpx

from app.core.config import Settings, get_settings
from app.models.enums import TariffCode
from app.services.tariffs import TariffPlan, get_tariff_plan


logger = logging.getLogger(__name__)


class YooKassaError(Exception):
    """Base YooKassa integration error."""


class YooKassaConfigurationError(YooKassaError):
    """Missing or invalid YooKassa credentials / settings."""


class YooKassaUpstreamError(YooKassaError):
    """YooKassa API returned an error or unexpected payload."""


@dataclass(frozen=True, slots=True)
class YooKassaPaymentCreated:
    """Result of creating a payment in YooKassa."""

    payment_id: str
    status: str
    amount_rub: Decimal
    currency: str
    confirmation_url: str | None
    description: str
    metadata: dict[str, str]
    raw: dict[str, Any]


class YooKassaService:
    """Thin async wrapper around YooKassa Payments API."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        shop_id = (self._settings.yookassa_shop_id or "").strip()
        secret = (
            self._settings.yookassa_secret_key.get_secret_value().strip()
            if self._settings.yookassa_secret_key is not None
            else ""
        )
        if not shop_id or not secret:
            raise YooKassaConfigurationError(
                "YOOKASSA_SHOP_ID and YOOKASSA_SECRET_KEY must be configured."
            )
        self._shop_id = shop_id
        self._secret_key = secret
        self._base_url = self._settings.yookassa_api_base_url.rstrip("/")
        self._return_url = self._settings.yookassa_return_url
        self._timeout = httpx.Timeout(self._settings.yookassa_timeout_seconds)

    def _auth(self) -> httpx.BasicAuth:
        return httpx.BasicAuth(self._shop_id, self._secret_key)

    async def create_tariff_payment(
        self,
        *,
        user_id: str,
        tariff_code: TariffCode | str,
        customer_email: str | None = None,
        idempotence_key: str | None = None,
        amount_rub_override: Decimal | None = None,
        discount_percent: int | None = None,
    ) -> YooKassaPaymentCreated:
        """Create a redirect payment for the given commercial tariff."""

        plan = get_tariff_plan(tariff_code)
        payload = self._build_payment_payload(
            plan=plan,
            user_id=user_id,
            customer_email=customer_email,
            amount_rub_override=amount_rub_override,
            discount_percent=discount_percent,
        )
        headers = {
            "Idempotence-Key": idempotence_key or str(uuid.uuid4()),
            "Content-Type": "application/json",
        }

        try:
            async with httpx.AsyncClient(
                base_url=self._base_url,
                auth=self._auth(),
                timeout=self._timeout,
            ) as client:
                response = await client.post("/payments", json=payload, headers=headers)
        except httpx.HTTPError as exc:
            raise YooKassaUpstreamError(f"YooKassa create payment failed: {exc}") from exc

        if response.status_code >= 400:
            raise YooKassaUpstreamError(
                f"YooKassa create payment HTTP {response.status_code}: {response.text}"
            )

        data = response.json()
        return self._parse_payment(data, plan=plan)

    async def get_payment(self, payment_id: str) -> dict[str, Any]:
        """Fetch payment object from YooKassa (webhook verification)."""

        if not payment_id or not payment_id.strip():
            raise YooKassaError("payment_id is required.")

        try:
            async with httpx.AsyncClient(
                base_url=self._base_url,
                auth=self._auth(),
                timeout=self._timeout,
            ) as client:
                response = await client.get(f"/payments/{payment_id.strip()}")
        except httpx.HTTPError as exc:
            raise YooKassaUpstreamError(f"YooKassa get payment failed: {exc}") from exc

        if response.status_code >= 400:
            raise YooKassaUpstreamError(
                f"YooKassa get payment HTTP {response.status_code}: {response.text}"
            )
        return response.json()

    def _build_payment_payload(
        self,
        *,
        plan: TariffPlan,
        user_id: str,
        customer_email: str | None,
        amount_rub_override: Decimal | None = None,
        discount_percent: int | None = None,
    ) -> dict[str, Any]:
        description = f"AI-Card-Master — тариф «{plan.title}»"
        if discount_percent is not None:
            description = (
                f"{description} (win-back −{discount_percent}%)"
            )
        amount_value = (
            f"{amount_rub_override:.2f}"
            if amount_rub_override is not None
            else plan.amount_value
        )
        payload: dict[str, Any] = {
            "amount": {
                "value": amount_value,
                "currency": "RUB",
            },
            "capture": True,
            "confirmation": {
                "type": "redirect",
                "return_url": self._return_url,
            },
            "description": description,
            "metadata": {
                "user_id": user_id,
                "tariff_code": plan.code.value,
            },
        }
        if discount_percent is not None:
            payload["metadata"]["winback_discount_percent"] = str(discount_percent)
        if customer_email:
            payload["receipt"] = {
                "customer": {"email": customer_email},
                "items": [
                    {
                        "description": description[:128],
                        "quantity": "1.00",
                        "amount": {
                            "value": amount_value,
                            "currency": "RUB",
                        },
                        "vat_code": self._settings.yookassa_vat_code,
                        "payment_mode": "full_payment",
                        "payment_subject": "service",
                    }
                ],
            }
        return payload

    def _parse_payment(
        self,
        data: dict[str, Any],
        *,
        plan: TariffPlan,
    ) -> YooKassaPaymentCreated:
        payment_id = str(data.get("id") or "").strip()
        if not payment_id:
            raise YooKassaUpstreamError("YooKassa response missing payment id.")

        amount_block = data.get("amount") or {}
        amount_value = Decimal(str(amount_block.get("value", plan.amount_value)))
        currency = str(amount_block.get("currency") or "RUB")

        confirmation = data.get("confirmation") or {}
        confirmation_url = confirmation.get("confirmation_url")
        if confirmation_url is not None:
            confirmation_url = str(confirmation_url)

        metadata_raw = data.get("metadata") or {}
        metadata = {str(k): str(v) for k, v in metadata_raw.items()}

        return YooKassaPaymentCreated(
            payment_id=payment_id,
            status=str(data.get("status") or "pending"),
            amount_rub=amount_value,
            currency=currency,
            confirmation_url=confirmation_url,
            description=str(data.get("description") or ""),
            metadata=metadata,
            raw=data,
        )


def get_yookassa_service() -> YooKassaService:
    """Factory for dependency injection."""

    return YooKassaService()
