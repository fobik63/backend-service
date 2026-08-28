"""Pydantic v2 schemas for AI-coin billing (YooKassa)."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.domain.coin_pricing import COIN_PACKAGES, MAX_PURCHASE_COINS, MIN_PURCHASE_COINS


class StrictBillingModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CoinPackResponse(StrictBillingModel):
    """One ready-made or quoted coin pack."""

    amount_coins: int
    unit_price_rub: str
    amount_rub: str
    currency: str = "RUB"
    package_code: str
    is_preset_package: bool
    description: str


class CreateCoinPaymentRequest(StrictBillingModel):
    """Start a YooKassa redirect checkout for AI-coins."""

    user_id: UUID = Field(..., description="Buyer user id (must match the JWT subject).")
    amount_coins: int = Field(
        ...,
        ge=MIN_PURCHASE_COINS,
        le=MAX_PURCHASE_COINS,
        description=(
            f"Any integer {MIN_PURCHASE_COINS}–{MAX_PURCHASE_COINS}, or a preset pack "
            f"{list(COIN_PACKAGES)}."
        ),
    )

    @field_validator("amount_coins")
    @classmethod
    def validate_amount_coins(cls, value: int) -> int:
        if value < MIN_PURCHASE_COINS:
            raise ValueError(f"Minimum purchase is {MIN_PURCHASE_COINS} AI-coins.")
        if value > MAX_PURCHASE_COINS:
            raise ValueError(f"Maximum purchase is {MAX_PURCHASE_COINS} AI-coins.")
        return value


class CreateCoinPaymentResponse(StrictBillingModel):
    """Checkout payload returned to the frontend."""

    payment_id: UUID
    yookassa_payment_id: str
    user_id: UUID
    amount_coins: int
    amount_rub: str
    unit_price_rub: str
    currency: str
    package_code: str
    status: str
    confirmation_url: str | None
    description: str | None
    idempotency_key: str


class YooKassaWebhookAckResponse(StrictBillingModel):
    """YooKassa expects a quick HTTP 200 acknowledgement."""

    success: bool = True
    detail: str
    already_processed: bool = False
    coins_credited: int = 0
