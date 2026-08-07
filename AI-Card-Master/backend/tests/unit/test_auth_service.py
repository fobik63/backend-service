"""Unit tests for AuthService register/login."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from app.application.auth_service import (
    AuthConflictError,
    AuthCredentialsError,
    AuthService,
)
from app.domain.auth import LoginCommand, RegisterCommand
from app.domain.referral import generate_referral_code
from app.models.enums import SubscriptionStatus
from app.models.user import User


class _Repo:
    def __init__(self) -> None:
        self.by_id: dict[UUID, User] = {}
        self.by_email: dict[str, User] = {}

    async def get_by_email(self, email: str) -> User | None:
        return self.by_email.get(email)

    async def get_by_id(self, user_id: UUID) -> User | None:
        return self.by_id.get(user_id)

    async def create_user(self, *, email: str, hashed_password: str) -> User:
        user = User(
            id=uuid4(),
            email=email,
            hashed_password=hashed_password,
            subscription_status=SubscriptionStatus.FREE,
            ai_coins=0,
            referral_code=generate_referral_code(),
            created_at=datetime.now(UTC),
        )
        self.by_id[user.id] = user
        self.by_email[email] = user
        return user

    async def flag_user(self, user_id: UUID, *, reason: str) -> User | None:
        user = self.by_id.get(user_id)
        if user is None:
            return None
        user.is_flagged = True
        user.flag_reason = reason
        return user


@pytest.mark.asyncio
async def test_register_and_login_roundtrip() -> None:
    service = AuthService(_Repo())
    view, tokens = await service.register(
        RegisterCommand(email="User@Example.COM", password="SecurePass1!")
    )
    assert view.email == "user@example.com"
    assert tokens.access_token
    # Without abuse context / trial deps the account is created with 0 coins.
    assert view.ai_coins == 0

    logged, login_tokens = await service.login(
        LoginCommand(email="user@example.com", password="SecurePass1!")
    )
    assert logged.id == view.id
    assert login_tokens.access_token


@pytest.mark.asyncio
async def test_register_conflict_and_bad_login() -> None:
    service = AuthService(_Repo())
    await service.register(
        RegisterCommand(email="a@example.com", password="SecurePass1!")
    )
    with pytest.raises(AuthConflictError):
        await service.register(
            RegisterCommand(email="a@example.com", password="SecurePass1!")
        )
    with pytest.raises(AuthCredentialsError):
        await service.login(
            LoginCommand(email="a@example.com", password="wrong-password")
        )
