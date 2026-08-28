"""User ORM model and related schema contracts."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base
from app.models.enums import SubscriptionStatus


class User(Base):
    """User table.

    Stores account credentials, subscription tier, expiry, and AI-coin balance.
    One generation consumes exactly one AI-coin.
    """

    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("ai_coins >= 0", name="ck_users_ai_coins_non_negative"),
        CheckConstraint(
            "daily_bonus_streak >= 0",
            name="ck_users_daily_bonus_streak_non_negative",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
        server_default=text("gen_random_uuid()"),
    )
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(1024), nullable=False)
    is_admin: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("false"),
        index=True,
    )
    subscription_status: Mapped[SubscriptionStatus] = mapped_column(
        Enum(
            SubscriptionStatus,
            name="subscription_status_enum",
            native_enum=True,
            create_constraint=False,
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        nullable=False,
        default=SubscriptionStatus.FREE,
        server_default=text("'Free'"),
    )
    # Balance of ИИкоины. 1 generation = 1 coin.
    ai_coins: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
    )
    subscription_ends_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=None,
    )
    daily_bonus_claimed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=None,
    )
    daily_bonus_streak: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
    )
    referral_code: Mapped[str | None] = mapped_column(
        String(16),
        unique=True,
        nullable=True,
        index=True,
    )
    referred_by_user_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    referral_bonus_granted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=None,
    )
    is_banned: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("false"),
        index=True,
    )
    ban_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    banned_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=None,
    )
    # Silent ban: account looks normal to the client; abuse controls apply in-band.
    is_flagged: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("false"),
        index=True,
    )
    flag_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Device fingerprint (SHA-256 hex) for anti-abuse correlation; nullable = legacy rows.
    fingerprint_hash: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        index=True,
    )
    last_seen_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=None,
        index=True,
    )
    telegram_id: Mapped[int | None] = mapped_column(
        BigInteger,
        nullable=True,
        unique=True,
        index=True,
    )
    # Encrypted seller API secrets for direct cabinet publish (AES-256-GCM).
    wb_api_token_ciphertext: Mapped[str | None] = mapped_column(Text, nullable=True)
    ozon_client_id_ciphertext: Mapped[str | None] = mapped_column(Text, nullable=True)
    ozon_api_key_ciphertext: Mapped[str | None] = mapped_column(Text, nullable=True)
    marketplace_credentials_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=None,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
        index=True,
    )

    generations = relationship("Generation", back_populates="user", cascade="all, delete-orphan")
    generation_jobs = relationship(
        "GenerationJob",
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    generation_error_logs = relationship(
        "GenerationErrorLog",
        back_populates="user",
        passive_deletes=True,
    )
    payments = relationship(
        "Payment",
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    coin_purchases = relationship(
        "CoinPurchase",
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    referred_by = relationship(
        "User",
        remote_side=[id],
        foreign_keys=[referred_by_user_id],
        back_populates="referrals",
    )
    referrals = relationship(
        "User",
        foreign_keys=[referred_by_user_id],
        back_populates="referred_by",
        passive_deletes=True,
    )
    winback_offers = relationship(
        "WinbackOffer",
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
