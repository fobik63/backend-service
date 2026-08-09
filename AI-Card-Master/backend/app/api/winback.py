"""Win-back / Churn Prevention API: cancel intent, offers, Telegram link."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies.auth import get_current_user
from app.api.payments import require_billing_access
from app.application.winback_service import (
    WinbackNotFoundError,
    WinbackService,
    WinbackValidationError,
)
from app.core.config import get_settings
from app.infrastructure.persistence.winback_repository import WinbackRepository
from app.models.database import get_db_session
from app.models.user import User
from app.services.telegram_user_notify import TelegramUserNotifier

router = APIRouter(prefix="/api/v1/winback", tags=["winback"])


class StrictAPIModel(BaseModel):
    """Strict Pydantic v2 base for win-back responses."""

    model_config = ConfigDict(extra="forbid", strict=True)


class LinkTelegramRequest(StrictAPIModel):
    """Bind the user's Telegram chat id for trigger messages."""

    telegram_id: int = Field(..., description="Telegram user/chat id")


class LinkTelegramResponse(StrictAPIModel):
    """Confirmation that Telegram was linked."""

    linked: bool
    telegram_id: int


class WinbackOfferResponse(StrictAPIModel):
    """One-shot retention offer shown on cancel / inactivity."""

    id: UUID
    trigger: str
    offer_type: str
    status: str
    title: str
    message: str
    free_generations: int | None
    discount_percent: int | None
    expires_at: str
    claimed_at: str | None
    created_at: str


class ClaimOfferResponse(StrictAPIModel):
    """Result of claiming a pending win-back offer."""

    offer: WinbackOfferResponse
    coins_granted: int
    ai_coins: int | None


def _offer_response(offer) -> WinbackOfferResponse:
    return WinbackOfferResponse(
        id=offer.id,
        trigger=offer.trigger.value,
        offer_type=offer.offer_type.value,
        status=offer.status.value,
        title=offer.title,
        message=offer.message,
        free_generations=offer.free_generations,
        discount_percent=offer.discount_percent,
        expires_at=offer.expires_at.isoformat(),
        claimed_at=offer.claimed_at.isoformat() if offer.claimed_at is not None else None,
        created_at=offer.created_at.isoformat(),
    )


async def get_winback_service(
    db_session: AsyncSession = Depends(get_db_session),
) -> WinbackService:
    """Request-scoped win-back use case service."""

    settings = get_settings()
    return WinbackService(
        WinbackRepository(db_session),
        inactivity_days=settings.winback_inactivity_days,
        free_generations=settings.winback_free_generations,
        discount_percent=settings.winback_discount_percent,
        offer_ttl_hours=settings.winback_offer_ttl_hours,
        telegram=TelegramUserNotifier(),
    )


@router.post("/cancel-intent", response_model=WinbackOfferResponse)
async def register_cancel_intent(
    current_user: User = Depends(require_billing_access),
    winback: WinbackService = Depends(get_winback_service),
) -> WinbackOfferResponse:
    """Frontend hits this when the user opens the subscription cancel page."""

    await winback.touch_last_seen(current_user.id)
    try:
        offer = await winback.register_cancel_intent(current_user.id)
    except WinbackValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    return _offer_response(offer)


@router.get("/offer", response_model=WinbackOfferResponse | None)
async def get_current_offer(
    current_user: User = Depends(require_billing_access),
    winback: WinbackService = Depends(get_winback_service),
) -> WinbackOfferResponse | None:
    """Return the open retention offer for the current user, if any."""

    await winback.touch_last_seen(current_user.id)
    offer = await winback.get_current_offer(current_user.id)
    if offer is None:
        return None
    return _offer_response(offer)


@router.post("/offer/{offer_id}/claim", response_model=ClaimOfferResponse)
async def claim_offer(
    offer_id: UUID,
    current_user: User = Depends(require_billing_access),
    winback: WinbackService = Depends(get_winback_service),
) -> ClaimOfferResponse:
    """Claim 5 free generations or activate 30% next-month discount."""

    try:
        offer, new_balance = await winback.claim_offer(
            user_id=current_user.id,
            offer_id=offer_id,
        )
    except WinbackNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except WinbackValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    coins_granted = int(offer.free_generations or 0) if new_balance is not None else 0
    return ClaimOfferResponse(
        offer=_offer_response(offer),
        coins_granted=coins_granted,
        ai_coins=new_balance,
    )


@router.post("/telegram", response_model=LinkTelegramResponse)
async def link_telegram(
    payload: LinkTelegramRequest,
    current_user: User = Depends(get_current_user),
    winback: WinbackService = Depends(get_winback_service),
) -> LinkTelegramResponse:
    """Link Telegram for style-update and retention trigger messages."""

    try:
        await winback.link_telegram(
            user_id=current_user.id,
            telegram_id=payload.telegram_id,
        )
    except WinbackValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    return LinkTelegramResponse(linked=True, telegram_id=payload.telegram_id)
