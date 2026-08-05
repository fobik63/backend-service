"""Payments API: tariff catalog, YooKassa checkout, async payment webhooks."""

from __future__ import annotations

import json
import logging
from decimal import Decimal
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import InvalidTokenError, decode_and_validate_token
from app.models.database import get_db_session
from app.models.enums import TariffCode
from app.models.user import User
from app.services.billing_service import (
    BillingError,
    BillingNotFoundError,
    BillingResult,
    BillingService,
    BillingValidationError,
    describe_tariff,
)
from app.services.tariffs import list_tariff_plans
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
    return user


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


@router.post(
    "/create",
    response_model=CreatePaymentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_payment(
    payload: CreatePaymentRequest,
    current_user: User = Depends(get_current_user),
    billing: BillingService = Depends(get_billing_service),
    yookassa: YooKassaService = Depends(get_yookassa_dependency),
) -> CreatePaymentResponse:
    """Create a YooKassa payment and persist a pending local payment row."""

    try:
        created = await yookassa.create_tariff_payment(
            user_id=str(current_user.id),
            tariff_code=payload.tariff_code,
            customer_email=current_user.email,
        )
        payment = await billing.create_pending_payment(
            user_id=current_user.id,
            tariff_code=payload.tariff_code,
            yookassa_payment_id=created.payment_id,
            amount_rub=created.amount_rub,
            confirmation_url=created.confirmation_url,
            description=created.description or None,
            currency=created.currency,
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
