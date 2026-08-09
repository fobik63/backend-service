"""SQLAlchemy adapter implementing ``CoinWalletPort`` via BillingService (R1)."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.billing_service import BillingService


class SqlAlchemyCoinWallet:
    """Thin committing wrapper around ``BillingService.*_in_transaction``."""

    def __init__(self, session: AsyncSession, *, auto_commit: bool = True) -> None:
        self._billing = BillingService(session)
        self._session = session
        self._auto_commit = auto_commit

    async def _finish_write(self, user: object) -> None:
        await self._session.flush()
        if self._auto_commit:
            await self._session.commit()
        await self._session.refresh(user)

    async def debit_coins(self, *, user_id: UUID, amount: int) -> int:
        user = await self._billing.debit_coins_in_transaction(
            user_id=user_id, amount=amount
        )
        await self._finish_write(user)
        return int(user.ai_coins)

    async def refund_coins(self, *, user_id: UUID, amount: int) -> int:
        user = await self._billing.refund_coins_in_transaction(
            user_id=user_id, amount=amount
        )
        await self._finish_write(user)
        return int(user.ai_coins)

    async def credit_coins(self, *, user_id: UUID, amount: int) -> int:
        user = await self._billing.credit_coins_in_transaction(
            user_id=user_id, amount=amount
        )
        await self._finish_write(user)
        return int(user.ai_coins)
