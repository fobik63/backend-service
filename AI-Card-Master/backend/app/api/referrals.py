"""Referral API: code application and current-user statistics."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies.auth import get_current_user
from app.application.referral_service import (
    ReferralNotFoundError,
    ReferralService,
    ReferralValidationError,
)
from app.core.config import get_settings
from app.infrastructure.persistence.referral_repository import ReferralRepository
from app.models.database import get_db_session
from app.models.user import User

router = APIRouter(prefix="/api/v1/referrals", tags=["referrals"])


class ApplyReferralRequest(BaseModel):
    """Referral code submitted by a newly invited user."""

    model_config = ConfigDict(extra="forbid", strict=True)

    referral_code: str = Field(..., min_length=1, max_length=32)


class ApplyReferralResponse(BaseModel):
    """Result of linking the current user to an inviter."""

    model_config = ConfigDict(extra="forbid", strict=True)

    applied: bool
    referrer_user_id: UUID


class ReferralStatsResponse(BaseModel):
    """Current user's referral code and earned bonus counters."""

    model_config = ConfigDict(extra="forbid", strict=True)

    referral_code: str
    invited_count: int
    paid_invited_count: int
    earned_free_credits: int
    bonus_credits_per_friend: int


async def get_referral_service(
    db_session: AsyncSession = Depends(get_db_session),
) -> ReferralService:
    """Request-scoped referral use case service."""

    return ReferralService(
        ReferralRepository(db_session),
        bonus_credits_per_friend=get_settings().referral_bonus_coins,
    )


@router.get("/stats", response_model=ReferralStatsResponse)
async def get_referral_stats(
    current_user: User = Depends(get_current_user),
    referrals: ReferralService = Depends(get_referral_service),
) -> ReferralStatsResponse:
    """Return referral code and counters for the authenticated user."""

    try:
        stats = await referrals.get_stats(current_user.id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return ReferralStatsResponse(
        referral_code=stats.referral_code,
        invited_count=stats.invited_count,
        paid_invited_count=stats.paid_invited_count,
        earned_free_credits=stats.earned_free_credits,
        bonus_credits_per_friend=stats.bonus_credits_per_friend,
    )


@router.post("/apply", response_model=ApplyReferralResponse)
async def apply_referral_code(
    payload: ApplyReferralRequest,
    current_user: User = Depends(get_current_user),
    referrals: ReferralService = Depends(get_referral_service),
) -> ApplyReferralResponse:
    """Attach an inviter to the current user before their first payment."""

    try:
        referrer_id = await referrals.apply_referral_code(
            user_id=current_user.id,
            referral_code=payload.referral_code,
        )
    except ReferralNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ReferralValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    return ApplyReferralResponse(applied=True, referrer_user_id=referrer_id)
