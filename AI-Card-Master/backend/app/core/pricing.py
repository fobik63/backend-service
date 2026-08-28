"""Flexible operation pricing matrix and Safe-Spend coin holds.

Tariff registry (``PRICING_MATRIX``) covers card generation, 3D modes,
texture/polycount/model coefficients, and per-minute GPU rental.
``BillingService`` calculates cost before enqueue and freezes coins via
``coin_holds`` until commit (success) or refund (failure/cancel).

Actual balance mutations still go through ``app.services.billing_service``
(single write-path / audit R1).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any, Mapping
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings


class PricingError(Exception):
    """Base pricing / operation-billing failure."""


class PricingValidationError(PricingError, ValueError):
    """Invalid service type, mode, or pricing params."""


class PricingNotFoundError(PricingError):
    """Hold transaction or related row was not found."""


class ServiceType(StrEnum):
    """Billable product surface."""

    CARD_GENERATION = "card_generation"
    THREE_D = "three_d"
    GPU_RENTAL = "gpu_rental"
    BRAND_LORA = "brand_lora"


class CoinHoldStatus(StrEnum):
    HELD = "held"
    CAPTURED = "captured"
    REFUNDED = "refunded"
    PARTIALLY_SETTLED = "partially_settled"


# --- Tariff registry (Pricing Matrix) -----------------------------------------

THREE_D_MODE_BASE_COINS: Mapping[str, int] = {
    "draft": 10,
    "standard": 30,
    "hd": 60,
}

# Multipliers applied on top of the 3D mode base.
THREE_D_POLYCOUNT_COEFFICIENTS: tuple[tuple[int, Decimal], ...] = (
    (30_000, Decimal("1.00")),
    (100_000, Decimal("1.15")),
    (300_000, Decimal("1.35")),
    (2_000_000, Decimal("1.60")),
)

THREE_D_TEXTURE_COEFFICIENTS: Mapping[str, Decimal] = {
    "1k": Decimal("1.00"),
    "1024": Decimal("1.00"),
    "2k": Decimal("1.20"),
    "2048": Decimal("1.20"),
    "4k": Decimal("1.45"),
    "4096": Decimal("1.45"),
}

THREE_D_MODEL_COEFFICIENTS: Mapping[str, Decimal] = {
    "default": Decimal("1.00"),
    "stub": Decimal("1.00"),
    "mock": Decimal("1.00"),
    "meshy": Decimal("1.00"),
    "tripo": Decimal("1.05"),
    "tripo3d": Decimal("1.05"),
    "rodin": Decimal("1.10"),
    "csmlib": Decimal("1.10"),
    "premium": Decimal("1.25"),
}

GPU_RENTAL_COINS_PER_MINUTE: Mapping[str, int] = {
    "rtx_4090": 2,
    "rtx4090": 2,
    "rtx_4080": 2,
    "a100": 5,
    "a100_40gb": 5,
    "a100_80gb": 6,
    "h100": 8,
    "stub": 1,
    "gpu.stub.1x": 1,
}


@dataclass(frozen=True, slots=True)
class PricingQuote:
    """Resolved coin quote for one operation."""

    service_type: str
    mode: str
    base_coins: int
    multiplier: Decimal
    total_coins: int


def _as_mapping(params: Mapping[str, Any] | None) -> dict[str, Any]:
    if params is None:
        return {}
    return dict(params)


def _normalise_mode(mode: str | None, *, default: str) -> str:
    cleaned = (mode or default).strip().lower()
    if not cleaned:
        return default
    return cleaned


def _texture_key(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        n = int(value)
        if n <= 1024:
            return "1k"
        if n <= 2048:
            return "2k"
        return "4k"
    text = str(value).strip().lower().replace(" ", "")
    if text.endswith("k") and text[:-1].isdigit():
        return text
    if text.isdigit():
        return _texture_key(int(text))
    return text or None


def _polycount_coefficient(polycount_target: object | None) -> Decimal:
    if polycount_target is None:
        return Decimal("1.00")
    try:
        target = int(polycount_target)
    except (TypeError, ValueError) as exc:
        raise PricingValidationError(
            "polycount_target must be an integer when provided."
        ) from exc
    if target <= 0:
        raise PricingValidationError("polycount_target must be positive.")
    for upper, coeff in THREE_D_POLYCOUNT_COEFFICIENTS:
        if target <= upper:
            return coeff
    return THREE_D_POLYCOUNT_COEFFICIENTS[-1][1]


def _texture_coefficient(texture_resolution: object | None) -> Decimal:
    key = _texture_key(texture_resolution)
    if key is None:
        return Decimal("1.00")
    if key in THREE_D_TEXTURE_COEFFICIENTS:
        return THREE_D_TEXTURE_COEFFICIENTS[key]
    # Unknown label: treat as 1K baseline (no surcharge).
    return Decimal("1.00")


def _model_coefficient(model: object | None) -> Decimal:
    if model is None:
        return Decimal("1.00")
    key = str(model).strip().lower()
    if not key:
        return Decimal("1.00")
    return THREE_D_MODEL_COEFFICIENTS.get(key, Decimal("1.00"))


def _gpu_rate_coins_per_minute(
    gpu_type: str,
    *,
    settings: Settings,
) -> int:
    key = gpu_type.strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "nvidia_rtx_4090": "rtx_4090",
        "nvidia_a100": "a100",
        "gpu.rtx4090.1x": "rtx_4090",
        "gpu.a100.1x": "a100",
    }
    key = aliases.get(key, key)
    if key in GPU_RENTAL_COINS_PER_MINUTE:
        return GPU_RENTAL_COINS_PER_MINUTE[key]
    # Fall back to configured stub rate for unknown cards.
    return max(0, int(settings.three_d_gpu_rental_coins_per_minute))


def _apply_multiplier(base: int, multiplier: Decimal) -> int:
    if base <= 0:
        return 0
    if multiplier <= 0:
        raise PricingValidationError("Pricing multiplier must be positive.")
    raw = Decimal(base) * multiplier
    return max(1, int(math.ceil(raw)))


def quote_cost(
    service_type: str,
    mode: str,
    params: Mapping[str, Any] | None = None,
    *,
    settings: Settings | None = None,
) -> PricingQuote:
    """Resolve a full pricing quote (base + coefficients)."""

    cfg = settings or get_settings()
    svc = service_type.strip().lower()
    payload = _as_mapping(params)

    if not cfg.generation_charge_coins:
        return PricingQuote(
            service_type=svc,
            mode=_normalise_mode(mode, default="default"),
            base_coins=0,
            multiplier=Decimal("1.00"),
            total_coins=0,
        )

    if svc in {ServiceType.CARD_GENERATION.value, "generation", "card"}:
        normalised = _normalise_mode(mode, default="fast")
        aliases = {
            "quick": "fast",
            "fast_generation": "fast",
            "hd": "hd_face_fix",
            "hd_quality": "hd_face_fix",
            "hd_quality_face_fix": "hd_face_fix",
            "hd_face_fix": "hd_face_fix",
            "fast": "fast",
        }
        normalised = aliases.get(normalised, normalised)
        if normalised == "hd_face_fix":
            base = int(cfg.generation_hd_face_fix_cost_coins)
        elif normalised == "fast":
            base = int(cfg.generation_fast_cost_coins)
        else:
            raise PricingValidationError(
                "card_generation mode must be 'fast' or 'hd_face_fix'."
            )
        return PricingQuote(
            service_type=ServiceType.CARD_GENERATION.value,
            mode=normalised,
            base_coins=base,
            multiplier=Decimal("1.00"),
            total_coins=max(0, base),
        )

    if svc in {ServiceType.THREE_D.value, "3d", "three-d"}:
        normalised = _normalise_mode(mode, default="standard")
        if normalised not in THREE_D_MODE_BASE_COINS:
            raise PricingValidationError(
                "three_d mode must be 'draft', 'standard', or 'hd'."
            )
        base = int(THREE_D_MODE_BASE_COINS[normalised])
        poly = _polycount_coefficient(payload.get("polycount_target"))
        tex = _texture_coefficient(
            payload.get("texture_resolution", payload.get("texture"))
        )
        model = _model_coefficient(
            payload.get("model", payload.get("provider_name", payload.get("provider")))
        )
        multiplier = poly * tex * model
        return PricingQuote(
            service_type=ServiceType.THREE_D.value,
            mode=normalised,
            base_coins=base,
            multiplier=multiplier,
            total_coins=_apply_multiplier(base, multiplier),
        )

    if svc in {ServiceType.GPU_RENTAL.value, "gpu", "gpu_rent"}:
        normalised = _normalise_mode(
            mode,
            default=str(
                payload.get("gpu_type")
                or payload.get("instance_type")
                or "stub"
            ),
        )
        gpu_type = str(
            payload.get("gpu_type")
            or payload.get("instance_type")
            or normalised
        )
        try:
            minutes = int(payload.get("minutes", 1))
        except (TypeError, ValueError) as exc:
            raise PricingValidationError("minutes must be an integer.") from exc
        if minutes < 0:
            raise PricingValidationError("minutes must be >= 0.")
        rate = _gpu_rate_coins_per_minute(gpu_type, settings=cfg)
        total = rate * minutes
        return PricingQuote(
            service_type=ServiceType.GPU_RENTAL.value,
            mode=gpu_type.strip().lower(),
            base_coins=rate,
            multiplier=Decimal(minutes),
            total_coins=max(0, total),
        )

    if svc in {ServiceType.BRAND_LORA.value, "lora", "brand-lora"}:
        base = int(cfg.brand_lora_training_cost_coins)
        return PricingQuote(
            service_type=ServiceType.BRAND_LORA.value,
            mode=_normalise_mode(mode, default="train"),
            base_coins=base,
            multiplier=Decimal("1.00"),
            total_coins=max(0, base),
        )

    raise PricingValidationError(f"Unknown service_type: {service_type!r}")


def calculate_cost(
    service_type: str,
    mode: str,
    params: Mapping[str, Any] | None = None,
    *,
    settings: Settings | None = None,
) -> int:
    """Return the exact coin amount required before starting a job."""

    return quote_cost(service_type, mode, params, settings=settings).total_coins


def generation_cost_for_mode(post_processing_mode: str | object) -> int:
    """Card-generation helper preserving FAST=1 / HD Face Fix=3 defaults."""

    mode = getattr(post_processing_mode, "value", post_processing_mode)
    return calculate_cost(ServiceType.CARD_GENERATION.value, str(mode), {})


class BillingService:
    """Operation pricing + Safe-Spend hold / capture / refund.

    Distinct from ``app.services.billing_service.BillingService`` (payments /
    wallet mutations). This façade owns the pricing matrix and ``coin_holds``
    ledger while delegating balance writes to the wallet service.
    """

    def __init__(
        self,
        session: AsyncSession,
        *,
        settings: Settings | None = None,
    ) -> None:
        self._session = session
        self._settings = settings
        self._wallet = None

    def _wallet_service(self):
        if self._wallet is None:
            from app.services.billing_service import BillingService as WalletBilling

            self._wallet = WalletBilling(self._session)
        return self._wallet

    def calculate_cost(
        self,
        service_type: str,
        mode: str,
        params: Mapping[str, Any] | None = None,
    ) -> int:
        """Calculate coins required before enqueue (no DB writes)."""

        return calculate_cost(
            service_type,
            mode,
            params,
            settings=self._settings or get_settings(),
        )

    def quote(
        self,
        service_type: str,
        mode: str,
        params: Mapping[str, Any] | None = None,
    ) -> PricingQuote:
        return quote_cost(
            service_type,
            mode,
            params,
            settings=self._settings or get_settings(),
        )

    async def hold_coins(
        self,
        user_id: UUID,
        amount: int,
        *,
        service_type: str | None = None,
        reference_id: UUID | None = None,
        idempotency_key: str | None = None,
        commit: bool = True,
    ) -> UUID:
        """Freeze ``amount`` coins; return ``transaction_id`` (coin_holds.id).

        When ``idempotency_key`` is set, Redis then Postgres
        ``idempotency_records`` are checked; a hit returns the prior
        ``transaction_id`` without a second freeze. On miss the ledger row
        is written in the same ACID transaction as the debit.
        """

        from app.models.coin_hold import CoinHold
        from app.services.billing_service import (
            BillingNotFoundError,
            BillingValidationError,
        )

        if amount < 0:
            raise BillingValidationError("Hold amount must be non-negative.")

        cleaned_key = idempotency_key.strip() if idempotency_key else None
        wallet = self._wallet_service()
        if cleaned_key:
            replay = await wallet.lookup_idempotency(
                user_id=user_id,
                idempotency_key=cleaned_key,
            )
            if replay is not None:
                prior = replay.response_body.get("transaction_id")
                if isinstance(prior, str) and prior:
                    return UUID(prior)
                raise BillingValidationError(
                    "Idempotent hold replay is missing transaction_id."
                )

        hold = CoinHold(
            id=uuid4(),
            user_id=user_id,
            amount=int(amount),
            remaining_amount=int(amount),
            captured_amount=0,
            status=CoinHoldStatus.HELD.value,
            service_type=(service_type.strip().lower() if service_type else None),
            reference_id=reference_id,
            idempotency_key=cleaned_key,
        )
        self._session.add(hold)

        try:
            mutation = await wallet.debit_coins_idempotent_in_transaction(
                user_id=user_id,
                amount=amount,
                idempotency_key=cleaned_key,
                response_body={
                    "operation": "hold",
                    "transaction_id": str(hold.id),
                    "service_type": hold.service_type,
                    "reference_id": str(reference_id) if reference_id else None,
                },
                response_code=200,
                operation="hold",
            )
        except BillingNotFoundError:
            raise
        except BillingValidationError:
            raise

        if mutation.already_processed:
            self._session.delete(hold)
            await self._session.flush()
            prior = mutation.response_body.get("transaction_id")
            if isinstance(prior, str) and prior:
                if commit:
                    await self._session.commit()
                return UUID(prior)
            raise BillingValidationError(
                "Idempotent hold replay is missing transaction_id."
            )

        await self._session.flush()
        if commit:
            await self._session.commit()
            await self._session.refresh(hold)
        return hold.id

    async def commit_or_refund(
        self,
        transaction_id: UUID,
        success: bool,
        *,
        commit: bool = True,
    ) -> CoinHoldStatus:
        """Capture held coins on success, or refund them on failure/cancel."""

        from app.models.coin_hold import CoinHold
        from app.services.billing_service import BillingNotFoundError

        hold = await self._session.get(
            CoinHold,
            transaction_id,
            with_for_update=True,
        )
        if hold is None:
            raise PricingNotFoundError(
                f"Coin hold transaction {transaction_id} was not found."
            )

        status = CoinHoldStatus(hold.status)
        if status is CoinHoldStatus.CAPTURED:
            return status
        if status is CoinHoldStatus.REFUNDED:
            return status
        if status is CoinHoldStatus.PARTIALLY_SETTLED:
            return status
        if status is not CoinHoldStatus.HELD:
            raise PricingValidationError(
                f"Coin hold {transaction_id} has unexpected status {hold.status!r}."
            )

        now = datetime.now(UTC)
        remaining = int(getattr(hold, "remaining_amount", hold.amount) or 0)
        captured = int(getattr(hold, "captured_amount", 0) or 0)
        if success:
            hold.status = CoinHoldStatus.CAPTURED.value
            hold.captured_amount = captured + remaining
            hold.remaining_amount = 0
            hold.settled_at = now
            hold.updated_at = now
            await self._session.flush()
            if commit:
                await self._session.commit()
            return CoinHoldStatus.CAPTURED

        if remaining > 0:
            try:
                await self._wallet_service().refund_coins_in_transaction(
                    user_id=hold.user_id,
                    amount=remaining,
                )
            except BillingNotFoundError as exc:
                raise PricingNotFoundError(str(exc)) from exc
        hold.remaining_amount = 0
        hold.settled_at = now
        hold.updated_at = now
        if captured > 0:
            hold.status = CoinHoldStatus.PARTIALLY_SETTLED.value
            await self._session.flush()
            if commit:
                await self._session.commit()
            return CoinHoldStatus.PARTIALLY_SETTLED
        hold.status = CoinHoldStatus.REFUNDED.value
        await self._session.flush()
        if commit:
            await self._session.commit()
        return CoinHoldStatus.REFUNDED
