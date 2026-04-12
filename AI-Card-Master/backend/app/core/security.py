"""Security utilities for password hashing and JWT tokens.

Implemented with security-first defaults suitable for modern backend systems:
- Argon2id password hashing via passlib;
- JWT creation and verification with strict claim validation;
- all secrets loaded from environment-backed settings.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.core.config import Settings, get_settings


class SecurityError(Exception):
    """Base security exception."""


class InvalidTokenError(SecurityError):
    """Raised when token is malformed, invalid, or expired."""


class PasswordVerificationError(SecurityError):
    """Raised when password verification process fails unexpectedly."""


def _build_password_context(settings: Settings) -> CryptContext:
    """Create passlib context with Argon2id profile.

    Argon2id is recommended for password storage due to GPU/ASIC resistance.
    """

    return CryptContext(
        schemes=["argon2"],
        deprecated="auto",
        argon2__type="ID",
        argon2__memory_cost=settings.argon2_memory_cost_kib,
        argon2__time_cost=settings.argon2_time_cost,
        argon2__parallelism=settings.argon2_parallelism,
    )


def _with_pepper(plain_password: str, settings: Settings) -> str:
    """Combine password with optional server-side pepper.

    Pepper is stored outside the database and helps reduce offline attack impact
    if password hashes are ever leaked.
    """

    pepper = settings.password_pepper.get_secret_value()
    if not pepper:
        return plain_password
    return f"{plain_password}{pepper}"


def hash_password(plain_password: str) -> str:
    """Hash password with Argon2id.

    Args:
        plain_password: Raw user password.

    Returns:
        Encoded hash suitable for database storage.
    """

    settings = get_settings()
    pwd_context = _build_password_context(settings)
    prepared_password = _with_pepper(plain_password, settings)
    return pwd_context.hash(prepared_password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify password against stored hash."""

    settings = get_settings()
    pwd_context = _build_password_context(settings)
    prepared_password = _with_pepper(plain_password, settings)

    try:
        return pwd_context.verify(prepared_password, hashed_password)
    except Exception as exc:  # pragma: no cover - defensive path
        raise PasswordVerificationError("Password verification failed.") from exc


def create_access_token(subject: str, additional_claims: dict[str, Any] | None = None) -> str:
    """Create short-lived access token with strict standard claims."""

    settings = get_settings()
    now = datetime.now(UTC)
    expires_at = now + timedelta(minutes=settings.jwt_access_token_ttl_minutes)

    payload: dict[str, Any] = {
        "sub": subject,
        "type": "access",
        "iss": settings.jwt_issuer,
        "aud": settings.jwt_audience,
        "iat": int(now.timestamp()),
        "nbf": int(now.timestamp()),
        "exp": int(expires_at.timestamp()),
        "jti": str(uuid4()),
    }
    if additional_claims:
        payload.update(additional_claims)

    return jwt.encode(
        payload,
        settings.jwt_secret_key.get_secret_value(),
        algorithm=settings.jwt_algorithm,
    )


def create_refresh_token(subject: str, additional_claims: dict[str, Any] | None = None) -> str:
    """Create long-lived refresh token."""

    settings = get_settings()
    now = datetime.now(UTC)
    expires_at = now + timedelta(days=settings.jwt_refresh_token_ttl_days)

    payload: dict[str, Any] = {
        "sub": subject,
        "type": "refresh",
        "iss": settings.jwt_issuer,
        "aud": settings.jwt_audience,
        "iat": int(now.timestamp()),
        "nbf": int(now.timestamp()),
        "exp": int(expires_at.timestamp()),
        "jti": str(uuid4()),
    }
    if additional_claims:
        payload.update(additional_claims)

    return jwt.encode(
        payload,
        settings.jwt_secret_key.get_secret_value(),
        algorithm=settings.jwt_algorithm,
    )


def decode_and_validate_token(token: str, expected_type: str | None = None) -> dict[str, Any]:
    """Decode JWT and validate claims.

    Args:
        token: JWT string to validate.
        expected_type: Optional strict check for `access` or `refresh` token.

    Returns:
        Decoded token payload.

    Raises:
        InvalidTokenError: Token is expired, malformed, or has invalid claims.
    """

    settings = get_settings()

    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret_key.get_secret_value(),
            algorithms=[settings.jwt_algorithm],
            audience=settings.jwt_audience,
            issuer=settings.jwt_issuer,
            options={
                "verify_signature": True,
                "verify_exp": True,
                "verify_iat": True,
                "verify_nbf": True,
                "verify_aud": True,
                "verify_iss": True,
                "require_sub": True,
                "require_exp": True,
                "require_iat": True,
                "require_nbf": True,
                "require_jti": True,
            },
        )
    except JWTError as exc:
        raise InvalidTokenError("Invalid or expired token.") from exc

    if expected_type is not None and payload.get("type") != expected_type:
        raise InvalidTokenError("Token type mismatch.")

    return payload
