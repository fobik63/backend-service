"""Payments API: tariff catalog, YooKassa checkout, async payment webhooks."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.security import InvalidTokenError, decode_and_validate_token
from app.infrastructure.persistence.winback_repository import WinbackRepository
from app.infrastructure.persistence.workspace_repository import WorkspaceRepository
from app.models.database import get_db_session
from app.models.enums import TariffCode
from app.models.user import User
from app.application.winback_service import WinbackService
from app.services.billing_service import (
    BillingError,
    BillingNotFoundError,
    BillingResult,
    BillingService,
    BillingValidationError,
    DailyBonusResult,
    describe_tariff,
)
from app.services.tariffs import get_tariff_plan, list_tariff_plans
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
bearer_scheme = HTTPBearer(auto_error=False)


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
    """Request-scoped billing service."""

    return BillingService(db_session)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Security(bearer_scheme),
    db_session: AsyncSession = Depends(get_db_session),
) -> User:
    """Resolve the authenticated user from a Bearer JWT access token."""

    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing bearer access token.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        payload = decode_and_validate_token(credentials.credentials, expected_type="access")
    except InvalidTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired access token.",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    subject = str(payload.get("sub") or "").strip()
    if not subject:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token subject is missing.",
        )

    try:
        user_id = UUID(subject)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token subject is not a valid user id.",
        ) from exc

    user = await db_session.scalar(select(User).where(User.id == user_id))
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found for this token.",
        )
    if user.is_banned:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User is banned for abuse.",
        )

    # Activity signal for Churn Prevention inactivity scanner (throttled in DB).
    now = datetime.now(UTC)
    last_seen = user.last_seen_at
    if last_seen is not None and last_seen.tzinfo is None:
        last_seen = last_seen.replace(tzinfo=UTC)
    if last_seen is None or (now - last_seen.astimezone(UTC)).total_seconds() >= 3600:
        user.last_seen_at = now
        await db_session.commit()
        await db_session.refresh(user)

    return user


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
async def list_tariffs() -> list[TariffResponse]:
    """Return the commercial tariff grid (Старт / Про / Полугодовой / Годовая)."""

    return [TariffResponse(**describe_tariff(plan)) for plan in list_tariff_plans()]


@router.get("/balance", response_model=BalanceResponse)
async def get_balance(
    current_user: User = Depends(require_billing_access),
) -> BalanceResponse:
    """Return AI-coin balance and daily bonus availability for the cabinet."""

    now = datetime.now(UTC)
    last_claimed_at = current_user.daily_bonus_claimed_at
    if last_claimed_at is not None and last_claimed_at.tzinfo is None:
        last_claimed_at = last_claimed_at.replace(tzinfo=UTC)
    daily_bonus_available = (
        last_claimed_at is None or last_claimed_at.astimezone(UTC).date() < now.date()
    )
    next_available_at = datetime(now.year, now.month, now.day, tzinfo=UTC) + timedelta(days=1)
    return BalanceResponse(
        ai_coins=current_user.ai_coins,
        daily_bonus_available=daily_bonus_available,
        daily_bonus_streak=current_user.daily_bonus_streak,
        daily_bonus_coins=get_settings().daily_bonus_coins,
        last_daily_bonus_claimed_at=last_claimed_at.isoformat()
        if last_claimed_at is not None
        else None,
        next_daily_bonus_available_at=next_available_at.isoformat(),
    )


@router.post("/daily-bonus/claim", response_model=DailyBonusClaimResponse)
async def claim_daily_bonus(
    current_user: User = Depends(require_billing_access),
    billing: BillingService = Depends(get_billing_service),
) -> DailyBonusClaimResponse:
    """Claim today's free AI-coin retention bonus exactly once."""

    try:
        result: DailyBonusResult = await billing.claim_daily_bonus(current_user.id)
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
    billing: BillingService = Depends(get_billing_service),
    yookassa: YooKassaService = Depends(get_yookassa_dependency),
    winback: WinbackService = Depends(get_winback_service_for_payments),
) -> CreatePaymentResponse:
    """Create a YooKassa payment and persist a pending local payment row."""

    plan = get_tariff_plan(payload.tariff_code)
    amount_rub, discount_percent, _offer_id = await winback.resolve_checkout_amount(
        user_id=current_user.id,
        catalog_price_rub=plan.price_rub,
    )

    try:
        created = await yookassa.create_tariff_payment(
            user_id=str(current_user.id),
            tariff_code=payload.tariff_code,
            customer_email=current_user.email,
            amount_rub_override=amount_rub if discount_percent is not None else None,
            discount_percent=discount_percent,
        )
        payment = await billing.create_pending_payment(
            user_id=current_user.id,
            tariff_code=payload.tariff_code,
            yookassa_payment_id=created.payment_id,
            amount_rub=created.amount_rub,
            confirmation_url=created.confirmation_url,
            description=created.description or None,
            currency=created.currency,
            discount_percent=discount_percent,
        )
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
    billing: BillingService = Depends(get_billing_service),
    yookassa: YooKassaService = Depends(get_yookassa_dependency),
    winback: WinbackService = Depends(get_winback_service_for_payments),
) -> WebhookAckResponse:
    """Receive asynchronous YooKassa notifications about payment status.

    Security: the webhook body is not trusted blindly. On ``payment.succeeded``
    we re-fetch the payment from YooKassa API and only then apply billing.
    """

    event = str(payload.get("event") or "").strip()
    obj = payload.get("object")
    if not isinstance(obj, dict):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Webhook payload missing payment object.",
        )

    yookassa_payment_id = str(obj.get("id") or "").strip()
    if not yookassa_payment_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Webhook payment id is missing.",
        )

    raw_payload = json.dumps(payload, ensure_ascii=False)

    if event == "payment.canceled":
        await billing.mark_payment_canceled(
            yookassa_payment_id=yookassa_payment_id,
            raw_payload=raw_payload,
        )
        return WebhookAckResponse(detail="Payment marked as canceled.")

    if event != "payment.succeeded":
        return WebhookAckResponse(detail=f"Ignored event '{event or 'unknown'}'.")

    try:
        verified = await yookassa.get_payment(yookassa_payment_id)
    except YooKassaConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    except (YooKassaUpstreamError, YooKassaError) as exc:
        logger.exception("Failed to verify YooKassa payment %s", yookassa_payment_id)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"YooKassa verification failed: {exc}",
        ) from exc

    if str(verified.get("status") or "").lower() != "succeeded":
        return WebhookAckResponse(
            detail=(
                f"Upstream payment status is '{verified.get('status')}', "
                "billing was not applied."
            )
        )

    amount_block = verified.get("amount") or {}
    try:
        expected_amount = Decimal(str(amount_block.get("value")))
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid amount in verified YooKassa payment.",
        ) from exc

    try:
        result: BillingResult = await billing.apply_successful_payment(
            yookassa_payment_id=yookassa_payment_id,
            expected_amount=expected_amount,
            raw_payload=raw_payload,
        )
    except BillingNotFoundError as exc:
        # Payment may arrive before local create finishes — ask YooKassa to retry.
        logger.warning("Webhook for unknown payment %s: %s", yookassa_payment_id, exc)
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except BillingValidationError as exc:
        logger.exception("Billing validation failed for %s", yookassa_payment_id)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except BillingError as exc:
        logger.exception("Billing failed for %s", yookassa_payment_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        ) from exc

    if not result.already_processed:
        payment = await billing.get_payment_by_yookassa_id(yookassa_payment_id)
        catalog_price = get_tariff_plan(result.tariff_code).price_rub
        if payment is not None and payment.amount_rub != catalog_price:
            _amount, _percent, offer_id = await winback.resolve_checkout_amount(
                user_id=result.user_id,
                catalog_price_rub=catalog_price,
            )
            await winback.redeem_discount_after_payment(
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
    return WebhookAckResponse(
        detail=detail,
        already_processed=result.already_processed,
    )
