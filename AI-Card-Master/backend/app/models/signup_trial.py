"""ORM model for signup trial fingerprint claims (anti-abuse)."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class SignupTrialClaim(Base):
    """One registration attempt's device fingerprint + trial grant outcome.

    ``fingerprint_hash`` is SHA-256(hex) of
    ``X-Device-Fingerprint + User-Agent + Accept-Language``.
    Rows with ``trial_granted=True`` permanently exhaust that hash.
    """

    __tablename__ = "signup_trial_claims"
    __table_args__ = (
        Index("ix_signup_trial_claims_fingerprint_hash", "fingerprint_hash"),
        Index(
            "ix_signup_trial_claims_fp_granted",
            "fingerprint_hash",
            "trial_granted",
        ),
        Index("ix_signup_trial_claims_ip_subnet", "ip_subnet"),
        Index("ix_signup_trial_claims_created_at", "created_at"),
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
    fingerprint_hash: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )
    client_ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    ip_subnet: Mapped[str | None] = mapped_column(String(64), nullable=True)
    trial_granted: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("false"),
    )
    denial_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(512), nullable=True)
    accept_language: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )
