"""SQLAlchemy adapter for ``IdempotencyRecordPort``."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.idempotency_record import IdempotencyRecord


class SqlAlchemyIdempotencyRecordRepository:
    """Flush-only persistence for durable billing idempotency."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(
        self, *, idempotency_key: str
    ) -> tuple[UUID, int, dict[str, Any]] | None:
        row = await self._session.get(IdempotencyRecord, idempotency_key)
        if row is None:
            return None
        body = row.response_body if isinstance(row.response_body, dict) else {}
        return row.user_id, int(row.response_code), dict(body)

    async def save_in_transaction(
        self,
        *,
        idempotency_key: str,
        user_id: UUID,
        response_code: int,
        response_body: dict[str, Any],
    ) -> None:
        self._session.add(
            IdempotencyRecord(
                idempotency_key=idempotency_key,
                user_id=user_id,
                response_code=int(response_code),
                response_body=dict(response_body),
            )
        )
        await self._session.flush()
