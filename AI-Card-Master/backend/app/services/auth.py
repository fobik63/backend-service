"""Refresh Token Rotation (RTR) with Token Families.

Security model:
- Every access/refresh pair shares a ``family_id`` (UUID) and each JWT has a unique ``jti``.
- On ``/auth/refresh`` the presented refresh ``jti`` is blacklisted (one-time use).
- A new pair is issued with the *same* ``family_id`` and a *new* ``jti``.
- Reuse of a blacklisted ``jti`` triggers FAMILY BURN: the whole family is revoked in Redis
  and the caller receives HTTP 401 ("Token family revoked due to reuse").
"""

from __future__ import annotations

import logging
import time
from uuid import UUID, uuid4

from app.application.ports.token_family import (
    TokenFamilyStorePort,
    TokenFamilyStoreUnavailableError,
)
from app.core.config import get_settings
from app.core.security import (
    InvalidTokenError,
    create_access_token,
    create_refresh_token,
    decode_and_validate_token,
)
from app.domain.auth import AuthTokens
from app.infrastructure.security.token_family_store import RedisTokenFamilyStore

logger = logging.getLogger(__name__)

FAMILY_REUSE_DETAIL = "Token family revoked due to reuse"


class TokenRotationError(Exception):
    """Base RTR error."""


class InvalidRefreshTokenError(TokenRotationError):
    """Refresh token is malformed, expired, or has invalid claims."""


class TokenFamilyRevokedError(TokenRotationError):
    """Token family was burned (reuse or explicit revoke)."""

    def __init__(self, message: str = FAMILY_REUSE_DETAIL) -> None:
        super().__init__(message)


class TokenRotationStoreError(TokenRotationError):
    """Security store (Redis) is unavailable for RTR."""


def _refresh_ttl_seconds() -> int:
    settings = get_settings()
    return max(60, int(settings.jwt_refresh_token_ttl_days) * 24 * 3600)


def _ttl_until_exp(exp_claim: object) -> int:
    """Remaining lifetime for a JWT ``exp`` claim (seconds), floored at 1."""

    try:
        exp = int(exp_claim)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return _refresh_ttl_seconds()
    remaining = exp - int(time.time())
    return max(1, remaining)


class RefreshTokenRotationService:
    """Issue and rotate JWT pairs with Redis-backed reuse detection."""

    def __init__(self, store: TokenFamilyStorePort | None = None) -> None:
        self._store: TokenFamilyStorePort = store or RedisTokenFamilyStore()

    def issue_token_pair(
        self,
        user_id: UUID,
        *,
        family_id: str | None = None,
    ) -> AuthTokens:
        """Create an access/refresh pair bound to a token family.

        Args:
            user_id: Authenticated subject.
            family_id: Existing family for rotation; omit to start a new family (login).
        """

        subject = str(user_id)
        resolved_family = (family_id or "").strip() or str(uuid4())
        claims = {"family_id": resolved_family}
        return AuthTokens(
            access_token=create_access_token(subject, additional_claims=claims),
            refresh_token=create_refresh_token(subject, additional_claims=claims),
        )

    async def rotate(self, refresh_token: str) -> AuthTokens:
        """Consume a refresh token and issue a rotated pair (same family, new jti).

        Raises:
            InvalidRefreshTokenError: Token invalid / wrong type / missing claims.
            TokenFamilyRevokedError: Family already burned or refresh jti reused.
            TokenRotationStoreError: Redis unavailable.
        """

        try:
            payload = decode_and_validate_token(
                refresh_token.strip(),
                expected_type="refresh",
            )
        except InvalidTokenError as exc:
            raise InvalidRefreshTokenError("Invalid or expired refresh token.") from exc

        subject = str(payload.get("sub") or "").strip()
        jti = str(payload.get("jti") or "").strip()
        family_id = str(payload.get("family_id") or "").strip()
        if not subject or not jti or not family_id:
            raise InvalidRefreshTokenError("Refresh token claims are incomplete.")

        try:
            user_id = UUID(subject)
        except ValueError as exc:
            raise InvalidRefreshTokenError(
                "Refresh token subject is not a valid user id."
            ) from exc

        family_ttl = _refresh_ttl_seconds()
        jti_ttl = _ttl_until_exp(payload.get("exp"))

        try:
            if await self._store.is_family_burned(family_id=family_id):
                logger.warning(
                    "Rejected refresh for burned family_id=%s user=%s",
                    family_id,
                    subject,
                )
                raise TokenFamilyRevokedError(FAMILY_REUSE_DETAIL)

            first_use = await self._store.blacklist_jti_if_new(
                jti=jti,
                ttl_seconds=jti_ttl,
            )
            if not first_use:
                # Reuse detection: steal signal — burn the entire family chain.
                await self._store.burn_family(
                    family_id=family_id,
                    ttl_seconds=family_ttl,
                )
                logger.warning(
                    "RTR reuse detected; burned family_id=%s user=%s jti=%s",
                    family_id,
                    subject,
                    jti,
                )
                raise TokenFamilyRevokedError(FAMILY_REUSE_DETAIL)
        except TokenFamilyStoreUnavailableError as exc:
            raise TokenRotationStoreError(
                "Token family store unavailable."
            ) from exc

        return self.issue_token_pair(user_id, family_id=family_id)

    async def is_family_revoked(self, family_id: str) -> bool:
        """Return whether ``family_id`` is burned (for access-token gatekeeping)."""

        value = (family_id or "").strip()
        if not value:
            return False
        try:
            return await self._store.is_family_burned(family_id=value)
        except TokenFamilyStoreUnavailableError:
            # Fail-open on access-path Redis blips: short-lived access tokens
            # still expire via ``exp``; refresh path remains fail-closed.
            logger.warning(
                "Redis unavailable for family revoke check; fail-open family_id=%s",
                value,
                exc_info=True,
            )
            return False


def get_refresh_token_rotation_service(
    store: TokenFamilyStorePort | None = None,
) -> RefreshTokenRotationService:
    """Composition helper for API / AuthService wiring."""

    return RefreshTokenRotationService(store=store)
