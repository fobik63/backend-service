"""User ORM model and related schema contracts."""

from __future__ import annotations

from uuid import UUID, uuid4

from sqlalchemy import Boolean, Enum, String, text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base
from app.models.enums import SubscriptionStatus


class User(Base):
    """User table.

    Stores account credentials and current subscription tier.
    """

    __tablename__ = "users"

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
        ),
        nullable=False,
        default=SubscriptionStatus.FREE,
        server_default=text("'Free'"),
    )

    generations = relationship("Generation", back_populates="user", cascade="all, delete-orphan")
    generation_error_logs = relationship(
        "GenerationErrorLog",
        back_populates="user",
        passive_deletes=True,
    )
