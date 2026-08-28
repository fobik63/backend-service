"""FastAPI billing module: AI-coin packs via YooKassa."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies.auth import get_current_user
from app.api.dependencies.yookassa_webhook import (
    YOOKASSA_WEBHOOK_ACK_DETAIL,
    log_yookassa_webhook_failure,
    require_yookassa_webhook_source,
)
from app.application.coin_billing_service import CoinBillingService
from app.domain.coin_pricing import list_coin_packages
from app.infrastructure.persistence.workspace_repository import WorkspaceRepository
from app.infrastructure.yookassa_sdk_client import get_yookassa_sdk_client
from app.models.database import get_db_session
from app.models.user import User
from app.schemas.billing import (
    CoinPackResponse,
    CreateCoinPaymentRequest,
    CreateCoinPaymentResponse,
    YooKassaWebhookAckResponse,
)
from app.services.billing_service import (
    BillingError,
    BillingValidationError,
)
from app.services.yookassa_service import (
    YooKassaConfigurationError,
    YooKassaError,
    YooKassaUpstreamError,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/billing", tags=["billing"])


async def require_billing_access(
    current_user: User = Depends(get_current_user),
    db_session: AsyncSession = Depends(get_db_session),
) -> User:
    """Block workspace managers from buying coins for the Pro owner."""

    if await WorkspaceRepository(db_session).is_workspace_manager(current_user.id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "Workspace managers have generation-only access and cannot "
                "purchase AI-coins."
            ),
        )
    return current_user


async def get_coin_billing_service(
    db_session: AsyncSession = Depends(get_db_session),
) -> CoinBillingService:
    """Request-scoped coin billing façade."""

    yookassa = None
    try:
        yookassa = get_yookassa_sdk_client()
    except YooKassaConfigurationError:
        yookassa = None
    return CoinBillingService(db_session, yookassa=yookassa)


@router.get("/coin-packs", response_model=list[CoinPackResponse])
async def list_packs() -> list[CoinPackResponse]:
    """Return ready-made coin packs (50 / 250 / 1000 / 5000)."""

    return [
        CoinPackResponse(
            amount_coins=quote.amount_coins,
            unit_price_rub=f"{quote.unit_price_rub:.4f}",
            amount_rub=quote.amount_value,
            currency=quote.currency,
            package_code=quote.package_code,
            is_preset_package=quote.is_preset_package,
            description=quote.description,
        )
        for quote in list_coin_packages()
    ]


@router.post(
    "/create-payment",
    response_model=CreateCoinPaymentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_payment(
    payload: CreateCoinPaymentRequest,
    current_user: User = Depends(require_billing_access),
    billing: CoinBillingService = Depends(get_coin_billing_service),
) -> CreateCoinPaymentResponse:
    """Create a YooKassa redirect payment for the requested coin amount."""

    if payload.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="user_id must match the authenticated account.",
        )

    try:
        checkout = await billing.create_checkout(
            user=current_user,
            amount_coins=payload.amount_coins,
        )
    except YooKassaConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    except (YooKassaUpstreamError, YooKassaError) as exc:
        logger.exception("YooKassa create coin payment failed")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"YooKassa error: {exc}",
        ) from exc
    except BillingValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except BillingError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        ) from exc

    purchase = checkout.purchase
    quote = checkout.quote
    return CreateCoinPaymentResponse(
        payment_id=purchase.id,
        yookassa_payment_id=purchase.yookassa_payment_id,
        user_id=purchase.user_id,
        amount_coins=purchase.amount_coins,
        amount_rub=f"{purchase.amount_rub:.2f}",
        unit_price_rub=f"{quote.unit_price_rub:.4f}",
        currency=purchase.currency,
        package_code=purchase.package_code,
        status=purchase.status.value,
        confirmation_url=purchase.confirmation_url,
        description=purchase.description,
        idempotency_key=checkout.idempotency_key,
    )


@router.post("/webhook/yookassa", response_model=YooKassaWebhookAckResponse)
async def yookassa_webhook(
    request: Request,
    payload: dict[str, Any],
    billing: CoinBillingService = Depends(get_coin_billing_service),
    _: None = Depends(require_yookassa_webhook_source),
) -> YooKassaWebhookAckResponse:
    """Receive YooKassa notifications.

    Security: source IP must be a published YooKassa range, and every event
    is applied only after ``Payment.find`` confirms upstream status.
    """

    try:
        result = await billing.process_yookassa_webhook(payload)
    except Exception as exc:
        log_yookassa_webhook_failure(exc, scope="coin")
        return YooKassaWebhookAckResponse(detail=YOOKASSA_WEBHOOK_ACK_DETAIL)

    return YooKassaWebhookAckResponse(
        detail=result.detail,
        already_processed=result.already_processed,
        coins_credited=result.coins_credited,
    )
