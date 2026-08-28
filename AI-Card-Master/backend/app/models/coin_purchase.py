"""SQLAlchemy model for standalone AI-coin purchases via YooKassa."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base
from app.models.enums import PaymentStatus


class CoinPurchase(Base):
    """Ledger row for one YooKassa coin top-up.

    Unique ``yookassa_payment_id`` plus ``SELECT … FOR UPDATE`` on webhook
    processing guarantees a payment credits coins at most once.
    """

    __tablename__ = "coin_purchases"
    __table_args__ = (
        UniqueConstraint("yookassa_payment_id", name="uq_coin_purchases_yookassa_payment_id"),
        UniqueConstraint("idempotency_key", name="uq_coin_purchases_idempotency_key"),
        CheckConstraint("amount_coins >= 50", name="ck_coin_purchases_min_coins"),
        CheckConstraint("amount_rub > 0", name="ck_coin_purchases_positive_amount"),
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
    amount_coins: Mapped[int] = mapped_column(Integer, nullable=False)
    unit_price_rub: Mapped[Decimal] = mapped_column(Numeric(10, 4), nullable=False)
    amount_rub: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(
        String(3),
        nullable=False,
        default="RUB",
        server_default=text("'RUB'"),
    )
    package_code: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    yookassa_payment_id: Mapped[str] = mapped_column(String(128), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[PaymentStatus] = mapped_column(
        Enum(
            PaymentStatus,
            name="payment_status_enum",
            native_enum=True,
            create_constraint=False,
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        nullable=False,
        default=PaymentStatus.PENDING,
        server_default=text("'pending'"),
        index=True,
    )
    confirmation_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    description: Mapped[str | None] = mapped_column(String(512), nullable=True)
    receipt_description: Mapped[str | None] = mapped_column(String(256), nullable=True)
    raw_webhook_payload: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
        index=True,
    )
    processed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=None,
    )

    user = relationship("User", back_populates="coin_purchases")
