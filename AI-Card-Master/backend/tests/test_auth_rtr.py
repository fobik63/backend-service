"""Integration tests: Refresh Token Rotation (RTR) + Token Families."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import fakeredis.aioredis
import pytest
from fastapi.testclient import TestClient

from app.api import auth as auth_api
from app.application.auth_service import AuthService
from app.core.security import decode_and_validate_token
from app.domain.referral import generate_referral_code
from app.infrastructure.security.token_family_store import RedisTokenFamilyStore
from app.main import app
from app.models.enums import SubscriptionStatus
from app.models.user import User
from app.services.auth import (
    FAMILY_REUSE_DETAIL,
    RefreshTokenRotationService,
    TokenFamilyRevokedError,
)


class _InMemoryAuthRepository:
    def __init__(self) -> None:
        self.by_id: dict[UUID, User] = {}
        self.by_email: dict[str, User] = {}

    async def get_by_email(self, email: str) -> User | None:
        return self.by_email.get(email.strip().lower())

    async def get_by_id(self, user_id: UUID) -> User | None:
        return self.by_id.get(user_id)

    async def create_user(
        self,
        *,
        email: str,
        hashed_password: str,
        fingerprint_hash: str | None = None,
    ) -> User:
        user = User(
            id=uuid4(),
            email=email.strip().lower(),
            hashed_password=hashed_password,
            subscription_status=SubscriptionStatus.FREE,
            ai_coins=0,
            referral_code=generate_referral_code(),
            is_admin=False,
            is_banned=False,
            is_flagged=False,
            fingerprint_hash=(fingerprint_hash or None),
            created_at=datetime.now(UTC),
        )
        self.by_id[user.id] = user
        self.by_email[user.email] = user
        return user

    async def update_fingerprint_hash(
        self,
        user_id: UUID,
        *,
        fingerprint_hash: str,
    ) -> User | None:
        user = self.by_id.get(user_id)
        if user is None:
            return None
        user.fingerprint_hash = fingerprint_hash[:64]
        return user

    async def exists_fingerprint_hash(
        self,
        *,
        fingerprint_hash: str,
        exclude_user_id: UUID | None = None,
    ) -> bool:
        for uid, user in self.by_id.items():
            if exclude_user_id is not None and uid == exclude_user_id:
                continue
            if user.fingerprint_hash == fingerprint_hash:
                return True
        return False

    async def flag_user(self, user_id: UUID, *, reason: str) -> User | None:
        user = self.by_id.get(user_id)
        if user is None:
            return None
        user.is_flagged = True
        user.flag_reason = reason
        return user


def _fake_rtr_stack() -> tuple[Any, RedisTokenFamilyStore, RefreshTokenRotationService]:
    fake_redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    store = RedisTokenFamilyStore(client=fake_redis)
    rotation = RefreshTokenRotationService(store=store)
    return fake_redis, store, rotation


@pytest.fixture
def rtr_client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """HTTP client with FakeRedis RTR store + in-memory auth repository."""

    from app.core.config import get_settings

    _fake_redis, store, rotation = _fake_rtr_stack()

    settings = get_settings()
    monkeypatch.setattr(settings, "security_suspicious_middleware_enabled", False)
    monkeypatch.setattr(settings, "security_input_sanitization_enabled", False)
    monkeypatch.setattr(settings, "security_behavioral_rate_enabled", False)
    monkeypatch.setattr(settings, "dead_mans_switch_enabled", False)
    monkeypatch.setattr(settings, "cloudflare_enabled", False)
    monkeypatch.setattr(settings, "cloudflare_enforce_edge", False)
    monkeypatch.setattr(settings, "slowapi_enabled", False)

    from app.core.rate_limit import limiter

    monkeypatch.setattr(limiter, "enabled", False)

    # Keep /auth/refresh and get_current_user on the same FakeRedis RTR store.
    monkeypatch.setattr(
        "app.services.auth.get_refresh_token_rotation_service",
        lambda store=None: rotation,
    )

    repo = _InMemoryAuthRepository()
    auth_service = AuthService(repo, token_rotation=rotation)

    async def _auth_dep() -> AuthService:
        return auth_service

    app.dependency_overrides[auth_api.get_auth_service] = _auth_dep
    client = TestClient(app)
    try:
        yield client
    finally:
        app.dependency_overrides.pop(auth_api.get_auth_service, None)


@pytest.mark.asyncio
async def test_rtr_successful_rotation_keeps_family_and_issues_new_jti() -> None:
    _fake_redis, store, rotation = _fake_rtr_stack()
    user_id = uuid4()

    original = rotation.issue_token_pair(user_id)
    first = decode_and_validate_token(original.refresh_token, expected_type="refresh")
    family_id = str(first["family_id"])
    first_jti = str(first["jti"])

    access_payload = decode_and_validate_token(
        original.access_token, expected_type="access"
    )
    assert access_payload["family_id"] == family_id
    assert access_payload["jti"] != first_jti

    rotated = await rotation.rotate(original.refresh_token)
    second = decode_and_validate_token(rotated.refresh_token, expected_type="refresh")

    assert second["family_id"] == family_id
    assert second["jti"] != first_jti
    assert rotated.refresh_token != original.refresh_token
    assert rotated.access_token != original.access_token
    assert await store.is_jti_blacklisted(jti=first_jti) is True
    assert await store.is_family_burned(family_id=family_id) is False


@pytest.mark.asyncio
async def test_rtr_reuse_burns_family_and_blocks_further_refresh() -> None:
    _fake_redis, store, rotation = _fake_rtr_stack()
    user_id = uuid4()

    original = rotation.issue_token_pair(user_id)
    first = decode_and_validate_token(original.refresh_token, expected_type="refresh")
    family_id = str(first["family_id"])

    # Legitimate rotation consumes the original jti.
    rotated = await rotation.rotate(original.refresh_token)
    second = decode_and_validate_token(rotated.refresh_token, expected_type="refresh")

    # Attacker (or lagging client) reuses the already-rotated refresh token.
    with pytest.raises(TokenFamilyRevokedError, match=FAMILY_REUSE_DETAIL):
        await rotation.rotate(original.refresh_token)

    assert await store.is_family_burned(family_id=family_id) is True

    # The previously valid successor in the same family is now dead.
    with pytest.raises(TokenFamilyRevokedError, match=FAMILY_REUSE_DETAIL):
        await rotation.rotate(rotated.refresh_token)

    assert second["family_id"] == family_id


def test_auth_refresh_endpoint_rotation_and_reuse_lockout(rtr_client: TestClient) -> None:
    email = f"rtr-{uuid4().hex[:10]}@example.com"
    password = "SecurePass1!"

    register = rtr_client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": password},
    )
    assert register.status_code == 201, register.text
    body = register.json()
    set_cookie = register.headers.get("set-cookie", "")
    assert "HttpOnly" in set_cookie
    assert "samesite=lax" in set_cookie.lower()
    assert body["tokens"]["refresh_token"] == ""
    refresh_token = register.cookies.get("refresh_token")
    assert refresh_token

    first_refresh = rtr_client.post("/api/v1/auth/refresh")
    assert first_refresh.status_code == 200, first_refresh.text
    rotated = first_refresh.json()["tokens"]
    rotated_refresh = first_refresh.cookies.get("refresh_token")
    assert rotated_refresh
    assert rotated_refresh != refresh_token
    assert rotated["access_token"]
    assert rotated["refresh_token"] == ""

    original_claims = decode_and_validate_token(refresh_token, expected_type="refresh")
    rotated_claims = decode_and_validate_token(
        rotated_refresh, expected_type="refresh"
    )
    assert rotated_claims["family_id"] == original_claims["family_id"]
    assert rotated_claims["jti"] != original_claims["jti"]

    # Reuse of the first refresh token → FAMILY BURN → 401.
    reuse = rtr_client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": refresh_token},
    )
    assert reuse.status_code == 401
    assert reuse.json()["detail"] == FAMILY_REUSE_DETAIL

    # Successor token from the burned family is also rejected.
    successor = rtr_client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": rotated_refresh},
    )
    assert successor.status_code == 401
    assert successor.json()["detail"] == FAMILY_REUSE_DETAIL

    # Access tokens bound to the burned family are force-logged-out immediately.
    me = rtr_client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {rotated['access_token']}"},
    )
    assert me.status_code == 401
    assert me.json()["detail"] == FAMILY_REUSE_DETAIL
