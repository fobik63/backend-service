"""Payments API: tariff catalog, YooKassa checkout, async payment webhooks."""

from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies.auth import get_current_user
from app.application.payment_service import PaymentApplicationService
from app.application.winback_service import WinbackService
from app.core.config import get_settings
from app.infrastructure.generation_history_cache import (
    get_cached_tariffs,
    set_cached_tariffs,
)
from app.infrastructure.payment_factory import build_payment_application_service
from app.infrastructure.persistence.winback_repository import WinbackRepository
from app.infrastructure.persistence.workspace_repository import WorkspaceRepository
from app.models.database import get_db_session
from app.models.enums import TariffCode
from app.models.user import User
from app.services.billing_service import (
    BillingError,
    BillingNotFoundError,
    BillingService,
    BillingValidationError,
    DailyBonusResult,
)
from app.services.telegram_user_notify import TelegramUserNotifier
from app.services.yookassa_service import (
    YooKassaConfigurationError,
    YooKassaError,
    YooKassaService,
    YooKassaUpstreamError,
    get_yookassa_service,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/payments", tags=["payments"])


class TariffResponse(BaseModel):
    """Public tariff card for the frontend pricing page."""

    code: str
    title: str
    duration_days: int
    ai_coins: int
    price_rub: float
    amount_value: str
    subscription_status: str
    description: str


class CreatePaymentRequest(BaseModel):
    """Start a YooKassa checkout for one commercial tariff."""

    tariff_code: TariffCode = Field(..., description="start | pro | half_year | year")


class CreatePaymentResponse(BaseModel):
    """Checkout payload returned to the frontend."""

    payment_id: str
    yookassa_payment_id: str
    tariff_code: str
    amount_rub: float
    currency: str
    status: str
    confirmation_url: str | None
    description: str | None


class WebhookAckResponse(BaseModel):
    """YooKassa expects a quick 200 acknowledgement."""

    success: bool = True
    detail: str
    already_processed: bool = False


class BalanceResponse(BaseModel):
    """Current user's AI-coin balance and daily retention bonus state."""

    model_config = ConfigDict(extra="forbid", strict=True)

    ai_coins: int
    daily_bonus_available: bool
    daily_bonus_streak: int
    daily_bonus_coins: int
    last_daily_bonus_claimed_at: str | None
    next_daily_bonus_available_at: str


class DailyBonusClaimResponse(BaseModel):
    """Result of claiming today's free retention bonus."""

    model_config = ConfigDict(extra="forbid", strict=True)

    claimed: bool
    coins_granted: int
    ai_coins: int
    daily_bonus_streak: int
    last_daily_bonus_claimed_at: str | None
    next_daily_bonus_available_at: str


async def get_billing_service(
    db_session: AsyncSession = Depends(get_db_session),
) -> BillingService:
    """Request-scoped billing service (kept for admin / legacy callers)."""

    return BillingService(db_session)


async def get_payment_application_service(
    db_session: AsyncSession = Depends(get_db_session),
) -> PaymentApplicationService:
    """Request-scoped payments façade for HTTP routers (audit A2).

    YooKassa is resolved lazily so catalog/balance endpoints work without
    payment credentials configured.
    """

    yookassa: YooKassaService | None
    try:
        yookassa = get_yookassa_service()
    except YooKassaConfigurationError:
        yookassa = None
    return build_payment_application_service(db_session, yookassa=yookassa)


async def get_winback_service_for_payments(
    db_session: AsyncSession = Depends(get_db_session),
) -> WinbackService:
    """Win-back service for discounted checkout and post-payment redemption."""

    settings = get_settings()
    return WinbackService(
        WinbackRepository(db_session),
        inactivity_days=settings.winback_inactivity_days,
        free_generations=settings.winback_free_generations,
        discount_percent=settings.winback_discount_percent,
        offer_ttl_hours=settings.winback_offer_ttl_hours,
        telegram=TelegramUserNotifier(),
    )


async def require_billing_access(
    current_user: User = Depends(get_current_user),
    db_session: AsyncSession = Depends(get_db_session),
) -> User:
    """Block workspace managers from payments and balance endpoints.

    Managers may generate cards but must not access billing for the Pro owner.
    """

    if await WorkspaceRepository(db_session).is_workspace_manager(current_user.id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "Workspace managers have generation-only access and cannot "
                "view or manage payments."
            ),
        )
    return current_user


async def get_yookassa_dependency() -> YooKassaService:
    """FastAPI dependency that maps config errors to HTTP 503."""

    try:
        return get_yookassa_service()
    except YooKassaConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc


@router.get("/tariffs", response_model=list[TariffResponse])
async def list_tariffs(
    payments: PaymentApplicationService = Depends(get_payment_application_service),
) -> list[TariffResponse]:
    """Return the commercial tariff grid (Pro Lite / Pro / Business)."""

    cached = await get_cached_tariffs()
    if cached is not None:
        try:
            return [
                TariffResponse.model_validate_json(json.dumps(item, ensure_ascii=False))
                for item in cached
            ]
        except (ValueError, TypeError):
            logger.debug("Tariffs cache payload invalid", exc_info=True)

    response = [TariffResponse(**item) for item in payments.list_tariffs()]
    await set_cached_tariffs([item.model_dump(mode="json") for item in response])
    return response


@router.get("/balance", response_model=BalanceResponse)
async def get_balance(
    current_user: User = Depends(require_billing_access),
    payments: PaymentApplicationService = Depends(get_payment_application_service),
) -> BalanceResponse:
    """Return AI-coin balance and daily bonus availability for the cabinet."""

    snap = payments.balance_snapshot(current_user)
    return BalanceResponse(
        ai_coins=snap.ai_coins,
        daily_bonus_available=snap.daily_bonus_available,
        daily_bonus_streak=snap.daily_bonus_streak,
        daily_bonus_coins=snap.daily_bonus_coins,
        last_daily_bonus_claimed_at=snap.last_daily_bonus_claimed_at.isoformat()
        if snap.last_daily_bonus_claimed_at is not None
        else None,
        next_daily_bonus_available_at=snap.next_daily_bonus_available_at.isoformat(),
    )


@router.post("/daily-bonus/claim", response_model=DailyBonusClaimResponse)
async def claim_daily_bonus(
    current_user: User = Depends(require_billing_access),
    payments: PaymentApplicationService = Depends(get_payment_application_service),
) -> DailyBonusClaimResponse:
    """Claim today's free AI-coin retention bonus exactly once."""

    try:
        result: DailyBonusResult = await payments.claim_daily_bonus(current_user.id)
    except BillingNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except BillingValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    return DailyBonusClaimResponse(
        claimed=result.claimed,
        coins_granted=result.coins_granted,
        ai_coins=result.new_balance,
        daily_bonus_streak=result.streak,
        last_daily_bonus_claimed_at=result.last_claimed_at.isoformat()
        if result.last_claimed_at is not None
        else None,
        next_daily_bonus_available_at=result.next_available_at.isoformat(),
    )


@router.post(
    "/create",
    response_model=CreatePaymentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_payment(
    payload: CreatePaymentRequest,
    current_user: User = Depends(require_billing_access),
    payments: PaymentApplicationService = Depends(get_payment_application_service),
) -> CreatePaymentResponse:
    """Create a YooKassa payment and persist a pending local payment row."""

    try:
        checkout = await payments.create_checkout(
            user=current_user,
            tariff_code=payload.tariff_code,
        )
        payment = checkout.payment
    except YooKassaConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    except (YooKassaUpstreamError, YooKassaError) as exc:
        logger.exception("YooKassa create payment failed")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"YooKassa error: {exc}",
        ) from exc
    except BillingValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except BillingNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except BillingError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        ) from exc

    return CreatePaymentResponse(
        payment_id=str(payment.id),
        yookassa_payment_id=payment.yookassa_payment_id,
        tariff_code=payment.tariff_code.value,
        amount_rub=float(payment.amount_rub),
        currency=payment.currency,
        status=payment.status.value,
        confirmation_url=payment.confirmation_url,
        description=payment.description,
    )


@router.post("/webhook", response_model=WebhookAckResponse)
async def yookassa_webhook(
    payload: dict[str, Any],
    payments: PaymentApplicationService = Depends(get_payment_application_service),
) -> WebhookAckResponse:
    """Receive asynchronous YooKassa notifications about payment status.

    Security: the webhook body is not trusted blindly. On ``payment.succeeded``
    we re-fetch the payment from YooKassa API and only then apply billing.
    """

    try:
        result = await payments.process_yookassa_webhook(payload)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except YooKassaConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    except (YooKassaUpstreamError, YooKassaError) as exc:
        logger.exception("Failed to verify YooKassa payment webhook")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"YooKassa verification failed: {exc}",
        ) from exc
    except BillingNotFoundError as exc:
        logger.warning("Webhook for unknown payment: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except BillingValidationError as exc:
        logger.exception("Billing validation failed for webhook")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except BillingError as exc:
        logger.exception("Billing failed for webhook")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        # Invalid Decimal / unexpected payload shape from verified amount.
        if "amount" in str(exc).lower() or isinstance(exc, (TypeError, ArithmeticError)):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid amount in verified YooKassa payment.",
            ) from exc
        raise

    return WebhookAckResponse(
        detail=result.detail,
        already_processed=result.already_processed,
    )
