"""Single write-path for AI-coin balance mutations (audit R1)."""

from __future__ import annotations

from typing import Protocol
from uuid import UUID


class CoinWalletPort(Protocol):
    """Atomic debit / refund / credit against ``users.ai_coins``.

    Implementations must use ``SELECT … FOR UPDATE`` and never leave a
    negative balance. Callers that share a unit-of-work should use the
    ``*_in_transaction`` methods on ``BillingService`` (flush only);
    committing wrappers belong at the application / repository edge.
    """

    async def debit_coins(self, *, user_id: UUID, amount: int) -> int:
        """Debit ``amount`` coins and commit; return the new balance."""

    async def refund_coins(self, *, user_id: UUID, amount: int) -> int:
        """Refund ``amount`` coins and commit; return the new balance."""

    async def credit_coins(self, *, user_id: UUID, amount: int) -> int:
        """Credit ``amount`` coins and commit; return the new balance."""
