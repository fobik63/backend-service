"""ORM model for Safe-Spend coin hold transactions."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class CoinHold(Base):
    """Frozen AI-coins reserved for an in-flight billable operation.

    Balance is debited at hold time; ``status`` transitions to ``captured``
    (keep debit) or ``refunded`` (restore balance) via
    ``app.core.pricing.BillingService.commit_or_refund``.
    """

    __tablename__ = "coin_holds"
    __table_args__ = (
        Index("ix_coin_holds_user_status", "user_id", "status"),
        Index("ix_coin_holds_reference_id", "reference_id"),
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
