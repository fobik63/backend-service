"""Port for durable financial idempotency records (Postgres outbox)."""

from __future__ import annotations

from typing import Any, Protocol
from uuid import UUID


class IdempotencyRecordPort(Protocol):
    """Lookup / persist idempotent coin-mutation outcomes."""

    async def get(
        self, *, idempotency_key: str
    ) -> tuple[UUID, int, dict[str, Any]] | None:
        """Return ``(user_id, response_code, response_body)`` or ``None``."""

    async def save_in_transaction(
        self,
        *,
        idempotency_key: str,
        user_id: UUID,
        response_code: int,
        response_body: dict[str, Any],
    ) -> None:
        """Insert a record without committing (caller owns the unit of work)."""
