"""Official ``yookassa`` Python SDK adapter (Payment.create / Payment.find).

The SDK is synchronous. Calls run in ``asyncio.to_thread`` so FastAPI handlers
stay non-blocking. Subscription tariff payments keep using the existing
async httpx client in ``app.services.yookassa_service``.
"""

from __future__ import annotations

import asyncio
import json
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID

from yookassa import Configuration
from yookassa import Payment as YooKassaSdkPayment
from yookassa.domain.exceptions import ApiError

from app.core.config import Settings, get_settings
from app.domain.coin_pricing import CoinPurchaseQuote
from app.services.yookassa_service import (
    YooKassaConfigurationError,
    YooKassaPaymentCreated,
    YooKassaUpstreamError,
)


class YooKassaSdkClient:
    """Thin async wrapper around the official YooKassa Payments SDK."""

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
        self._vat_code = self._settings.yookassa_vat_code

    def _configure_sdk(self) -> None:
        Configuration.account_id = self._shop_id
        Configuration.secret_key = self._secret_key

    def _build_create_params(
        self,
        *,
        quote: CoinPurchaseQuote,
        user_id: UUID,
        customer_email: str | None,
        return_url: str,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "amount": {
                "value": quote.amount_value,
                "currency": quote.currency,
            },
            "capture": True,
            "confirmation": {
                "type": "redirect",
                "return_url": return_url,
            },
            "description": quote.description[:128],
            "metadata": {
                "user_id": str(user_id),
                "amount_coins": str(quote.amount_coins),
                "package_code": quote.package_code,
                "product": "ai_coins",
            },
        }
        if customer_email:
            payload["receipt"] = {
                "customer": {"email": customer_email},
                "items": [
                    {
                        "description": quote.receipt_item_description[:128],
                        "quantity": "1.00",
                        "amount": {
                            "value": quote.amount_value,
                            "currency": quote.currency,
                        },
                        "vat_code": self._vat_code,
                        "payment_mode": "full_payment",
                        "payment_subject": "service",
                    }
                ],
            }
        return payload

    @staticmethod
    def _sdk_object_to_dict(payment: object) -> dict[str, Any]:
        json_fn = getattr(payment, "json", None)
        if callable(json_fn):
            raw = json_fn()
            if isinstance(raw, dict):
                return raw
            if isinstance(raw, str):
                parsed = json.loads(raw)
                if isinstance(parsed, dict):
                    return parsed
        dump_fn = getattr(payment, "to_dict", None)
        if callable(dump_fn):
            dumped = dump_fn()
            if isinstance(dumped, dict):
                return dumped
        raise YooKassaUpstreamError("YooKassa SDK returned an unreadable payment object.")

    def _parse_created(self, data: dict[str, Any]) -> YooKassaPaymentCreated:
        payment_id = str(data.get("id") or "").strip()
        if not payment_id:
            raise YooKassaUpstreamError("YooKassa response missing payment id.")

        amount_block = data.get("amount") or {}
        try:
            amount_value = Decimal(str(amount_block.get("value")))
        except (InvalidOperation, TypeError, ValueError) as exc:
            raise YooKassaUpstreamError(
                "YooKassa response has an invalid amount value."
            ) from exc

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
            currency=str(amount_block.get("currency") or "RUB"),
            confirmation_url=confirmation_url,
            description=str(data.get("description") or ""),
            metadata=metadata,
            raw=data,
        )

    async def create_coin_payment(
        self,
        *,
        quote: CoinPurchaseQuote,
        user_id: UUID,
        customer_email: str | None,
        idempotency_key: str,
        return_url: str,
    ) -> YooKassaPaymentCreated:
        """Create a redirect payment via ``Payment.create``."""

        params = self._build_create_params(
            quote=quote,
            user_id=user_id,
            customer_email=customer_email,
            return_url=return_url,
        )

        def _create() -> object:
            self._configure_sdk()
            return YooKassaSdkPayment.create(params, idempotency_key)

        try:
            created = await asyncio.to_thread(_create)
        except ApiError as exc:
            raise YooKassaUpstreamError(f"YooKassa Payment.create failed: {exc}") from exc
        except Exception as exc:
            raise YooKassaUpstreamError(
                f"YooKassa Payment.create failed: {exc}"
            ) from exc

        data = self._sdk_object_to_dict(created)
        return self._parse_created(data)

    async def find_payment(self, payment_id: str) -> dict[str, Any]:
        """Re-fetch a payment via ``Payment.find_one`` (webhook anti-forgery).

        Older YooKassa samples name this ``Payment.find``; current Python SDK
        exposes ``Payment.find_one`` for GET /payments/{id}.
        """

        cleaned = (payment_id or "").strip()
        if not cleaned:
            raise YooKassaUpstreamError("payment_id is required.")

        def _find() -> object:
            self._configure_sdk()
            return YooKassaSdkPayment.find_one(cleaned)

        try:
            found = await asyncio.to_thread(_find)
        except ApiError as exc:
            raise YooKassaUpstreamError(f"YooKassa Payment.find failed: {exc}") from exc
        except Exception as exc:
            raise YooKassaUpstreamError(f"YooKassa Payment.find failed: {exc}") from exc

        return self._sdk_object_to_dict(found)


def get_yookassa_sdk_client() -> YooKassaSdkClient:
    """Factory for dependency injection."""

    return YooKassaSdkClient()
