"""FastAPI dependency for CoinGuardService (same session as the request UoW)."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.coin_guard_service import CoinGuardService
from app.models.database import get_db_session


async def get_coin_guard_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> CoinGuardService:
    return CoinGuardService(session, auto_commit=False)
