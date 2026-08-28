"""FastAPI dependency: fail-fast 402 before SEO / review LLM routes run."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies.auth import get_current_user
from app.application.llm_coin_guard import LlmCoinGuard
from app.core.config import get_settings
from app.domain.llm_coin_guard import LlmCoinOperation
from app.models.database import get_db_session
from app.models.user import User
from app.services.billing_service import BillingService


def build_llm_coin_guard(
    db_session: AsyncSession,
    *,
    charge_coins: bool | None = None,
) -> LlmCoinGuard:
    settings = get_settings()
    enabled = (
        bool(settings.generation_charge_coins)
        if charge_coins is None
        else bool(charge_coins)
    )
    return LlmCoinGuard(
        db_session,
        billing=BillingService(db_session),
        charge_coins=enabled,
    )


async def get_llm_coin_guard(
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> LlmCoinGuard:
    return build_llm_coin_guard(db_session)


async def require_seo_card_coins(
    current_user: Annotated[User, Depends(get_current_user)],
    guard: Annotated[LlmCoinGuard, Depends(get_llm_coin_guard)],
) -> LlmCoinGuard:
    """Require enough coins for at least one SEO card (2 coins)."""

    await guard.assert_can_afford_unit(
        user_id=current_user.id,
        operation=LlmCoinOperation.SEO_CARD,
        quantity=1,
        balance_hint=int(current_user.ai_coins),
    )
    return guard


async def require_review_coins(
    current_user: Annotated[User, Depends(get_current_user)],
    guard: Annotated[LlmCoinGuard, Depends(get_llm_coin_guard)],
) -> LlmCoinGuard:
    """Require enough coins for at least one generated review (2 coins)."""

    await guard.assert_can_afford_unit(
        user_id=current_user.id,
        operation=LlmCoinOperation.REVIEW,
        quantity=1,
        balance_hint=int(current_user.ai_coins),
    )
    return guard
