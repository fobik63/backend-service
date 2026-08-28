"""ORM model for Safe-Spend coin hold transactions."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class CoinHold(Base):
    """Frozen AI-coins reserved for an in-flight billable operation.

    Balance is debited at hold time; ``status`` transitions to ``captured``
    (keep debit), ``refunded`` (restore remaining), or ``partially_settled``
    (keep captured, refund remaining) via CoinGuard / ``commit_or_refund``.
    """

    __tablename__ = "coin_holds"
    __table_args__ = (
        Index("ix_coin_holds_user_status", "user_id", "status"),
        Index("ix_coin_holds_reference_id", "reference_id"),
        UniqueConstraint("idempotency_key", name="uq_coin_holds_idempotency_key"),
        CheckConstraint("amount >= 0", name="ck_coin_holds_amount_non_negative"),
        CheckConstraint(
            "remaining_amount >= 0",
            name="ck_coin_holds_remaining_non_negative",
        ),
        CheckConstraint(
            "captured_amount >= 0",
            name="ck_coin_holds_captured_non_negative",
        ),
        CheckConstraint(
            "remaining_amount + captured_amount <= amount",
            name="ck_coin_holds_remaining_plus_captured_le_amount",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
        server_default=text("gen_random_uuid()"),
    )
    user_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    amount: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
    )
    remaining_amount: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
    )
    captured_amount: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
    )
    idempotency_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="held",
        server_default=text("'held'"),
        index=True,
    )
    service_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    reference_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("NOW()"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("NOW()"),
    )
    settled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
