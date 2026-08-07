"""Durable idempotency ledger for financial coin mutations (Transactional Outbox).

Redis is the hot path; ``idempotency_records`` is the ACID source of truth so
duplicate debit / hold cannot occur after Redis flush or outage.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Integer, String, text
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class IdempotencyRecord(Base):
    """Persisted outcome of an idempotent coin debit or freeze.

    Written in the same Postgres transaction as the balance mutation so a
    crash or Redis wipe cannot cause a second charge for the same key.
    """

    __tablename__ = "idempotency_records"

    idempotency_key: Mapped[str] = mapped_column(
        String(255),
        primary_key=True,
    )
    user_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    response_code: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )
    response_body: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
        index=True,
    )
