"""Application service: user registration and JWT login."""

from __future__ import annotations

from uuid import UUID

from app.application.ports.auth import AuthRepositoryPort
from app.core.security import (
    create_access_token,
    create_refresh_token,
    hash_password,
    verify_password,
)
from app.domain.auth import (
    AuthTokens,
    AuthUserView,
    LoginCommand,
    RegisterCommand,
)
from app.domain.referral import generate_referral_code
from app.models.user import User


class AuthError(Exception):
    """Base auth use-case error."""


class AuthConflictError(AuthError):
    """Email already registered."""


class AuthCredentialsError(AuthError):
    """Invalid email/password or banned account."""


class AuthNotFoundError(AuthError):
    """Authenticated subject no longer exists."""


def _to_view(user: User) -> AuthUserView:
    return AuthUserView(
        id=user.id,
        email=user.email,
        ai_coins=int(user.ai_coins or 0),
        subscription_status=str(user.subscription_status.value)
        if hasattr(user.subscription_status, "value")
        else str(user.subscription_status),
        is_admin=bool(user.is_admin),
        is_banned=bool(user.is_banned),
        created_at=user.created_at,
    )


def _issue_tokens(user_id: UUID) -> AuthTokens:
    subject = str(user_id)
    return AuthTokens(
        access_token=create_access_token(subject),
        refresh_token=create_refresh_token(subject),
    )


class AuthService:
    """Register and authenticate users against the auth repository port."""

    def __init__(self, repository: AuthRepositoryPort) -> None:
        self._repository = repository

    async def register(self, command: RegisterCommand) -> tuple[AuthUserView, AuthTokens]:
        existing = await self._repository.get_by_email(command.email)
        if existing is not None:
            raise AuthConflictError("Email is already registered.")

        user = await self._repository.create_user(
            email=command.email,
            hashed_password=hash_password(command.password),
        )
        if not user.referral_code:
            # Best-effort: repository may already assign a code.
            user.referral_code = generate_referral_code()
        return _to_view(user), _issue_tokens(user.id)

    async def login(self, command: LoginCommand) -> tuple[AuthUserView, AuthTokens]:
        user = await self._repository.get_by_email(command.email)
        if user is None or not verify_password(command.password, user.hashed_password):
            raise AuthCredentialsError("Invalid email or password.")
        if user.is_banned:
            raise AuthCredentialsError("User is banned for abuse.")
        return _to_view(user), _issue_tokens(user.id)

    async def get_profile(self, user_id: UUID) -> AuthUserView:
        user = await self._repository.get_by_id(user_id)
        if user is None:
            raise AuthNotFoundError("User not found.")
        if user.is_banned:
            raise AuthCredentialsError("User is banned for abuse.")
        return _to_view(user)
