"""Async YooKassa API client (payments create + retrieve for webhook verify).

Uses HTTP Basic auth (shopId:secretKey) against api.yookassa.ru/v3.
Official SDK is synchronous; this client stays async via httpx.

Timeouts and transport failures are mapped to ``YooKassaUpstreamError`` so the
API never crashes when the payment provider stalls.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx

from app.core.config import Settings, get_settings
from app.infrastructure.http_resilience import (
    TRANSIENT_HTTP_CODES,
    call_with_transport_retry,
)
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
        self._max_retries = self._settings.yookassa_max_retries
        self._base_retry_delay = self._settings.yookassa_base_retry_delay_seconds

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

        response = await self._request_with_retry(
            method="POST",
            path="/payments",
            headers=headers,
            json_body=payload,
            operation_name="YooKassa create payment",
        )
        data = self._parse_json_object(response, operation="create payment")
        return self._parse_payment(data, plan=plan)

    async def get_payment(self, payment_id: str) -> dict[str, Any]:
        """Fetch payment object from YooKassa (webhook verification)."""

        if not payment_id or not payment_id.strip():
            raise YooKassaError("payment_id is required.")

        response = await self._request_with_retry(
            method="GET",
            path=f"/payments/{payment_id.strip()}",
            headers={"Content-Type": "application/json"},
            json_body=None,
            operation_name="YooKassa get payment",
        )
        return self._parse_json_object(response, operation="get payment")

    async def find_payment(self, payment_id: str) -> dict[str, Any]:
        """SDK-named alias of ``get_payment`` (YooKassa ``Payment.find``)."""

        return await self.get_payment(payment_id)

    async def _request_with_retry(
        self,
        *,
        method: str,
        path: str,
        headers: dict[str, str],
        json_body: dict[str, Any] | None,
        operation_name: str,
    ) -> httpx.Response:
        """Execute HTTP call with transport + transient-status retries."""

        async def _once() -> httpx.Response:
            async with httpx.AsyncClient(
                base_url=self._base_url,
                auth=self._auth(),
                timeout=self._timeout,
            ) as client:
                return await client.request(
                    method,
                    path,
                    headers=headers,
                    json=json_body,
                )

        try:
            response = await call_with_transport_retry(
                _once,
                max_retries=self._max_retries,
                base_delay_seconds=self._base_retry_delay,
                operation_name=operation_name,
                is_transient_result=lambda r: r.status_code in TRANSIENT_HTTP_CODES,
            )
        except httpx.HTTPError as exc:
            raise YooKassaUpstreamError(
                f"{operation_name} failed after retries: {exc}"
            ) from exc

        if response.status_code >= 400:
            raise YooKassaUpstreamError(
                f"{operation_name} HTTP {response.status_code}: {response.text[:500]}"
            )
        return response

    @staticmethod
    def _parse_json_object(response: httpx.Response, *, operation: str) -> dict[str, Any]:
        try:
            data = response.json()
        except ValueError as exc:
            raise YooKassaUpstreamError(
                f"YooKassa {operation} returned non-JSON body."
            ) from exc
        if not isinstance(data, dict):
            raise YooKassaUpstreamError(
                f"YooKassa {operation} returned a non-object payload."
            )
        return data

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
        try:
            amount_value = Decimal(str(amount_block.get("value", plan.amount_value)))
        except (InvalidOperation, TypeError, ValueError) as exc:
            raise YooKassaUpstreamError(
                "YooKassa response has an invalid amount value."
            ) from exc
        currency = str(amount_block.get("currency") or "RUB")

        confirmation = data.get("confirmation") or {}
        confirmation_url = confirmation.get("confirmation_url")
        if confirmation_url is not None:
            confirmation_url = str(confirmation_url)

        metadata_raw = data.get("metadata") or {}
        if not isinstance(metadata_raw, dict):
            metadata_raw = {}
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
