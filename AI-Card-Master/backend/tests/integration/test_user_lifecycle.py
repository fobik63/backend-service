"""Integration: full user lifecycle via TestClient (auth → profile → product APIs)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi import Depends, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.testclient import TestClient

from app.api import ab_tests as ab_tests_api
from app.api import analytics as analytics_api
from app.api import auth as auth_api
from app.api import payments as payments_api
from app.application.ab_test_service import AbTestService
from app.application.auth_service import AuthService
from app.application.payment_service import BalanceSnapshot
from app.application.style_analytics_service import StyleAnalyticsService
from app.core.config import get_settings
from app.core.security import InvalidTokenError, decode_and_validate_token
from app.domain.referral import generate_referral_code
from app.main import app
from app.models.enums import SubscriptionStatus
from app.models.user import User


class InMemoryAuthRepository:
    """Async auth repository used by the lifecycle integration test."""

    def __init__(self) -> None:
        self.by_id: dict[UUID, User] = {}
        self.by_email: dict[str, User] = {}

    async def get_by_email(self, email: str) -> User | None:
        return self.by_email.get(email.strip().lower())

    async def get_by_id(self, user_id: UUID) -> User | None:
        return self.by_id.get(user_id)

    async def create_user(self, *, email: str, hashed_password: str) -> User:
        user = User(
            id=uuid4(),
            email=email.strip().lower(),
            hashed_password=hashed_password,
            subscription_status=SubscriptionStatus.FREE,
            ai_coins=5,
            referral_code=generate_referral_code(),
            is_admin=False,
            is_banned=False,
            is_flagged=False,
            daily_bonus_streak=0,
            created_at=datetime.now(UTC),
        )
        self.by_id[user.id] = user
        self.by_email[user.email] = user
        return user

    async def flag_user(self, user_id: UUID, *, reason: str) -> User | None:
        user = self.by_id.get(user_id)
        if user is None:
            return None
        user.is_flagged = True
        user.flag_reason = reason
        return user


class _EmptyStyleRepo:
    async def aggregate_styles_since(self, **_: Any) -> list:
        return []

    async def aggregate_niches_since(self, **_: Any) -> list:
        return []


class _FakePayments:
    def __init__(self, *, daily_bonus_coins: int = 1) -> None:
        self._daily_bonus_coins = daily_bonus_coins

    def balance_snapshot(self, user: User) -> BalanceSnapshot:
        now = datetime.now(UTC)
        return BalanceSnapshot(
            ai_coins=int(user.ai_coins),
            daily_bonus_available=True,
            daily_bonus_streak=int(user.daily_bonus_streak or 0),
            daily_bonus_coins=self._daily_bonus_coins,
            last_daily_bonus_claimed_at=None,
            next_daily_bonus_available_at=datetime(
                now.year, now.month, now.day, tzinfo=UTC
            )
            + timedelta(days=1),
        )


@pytest.fixture
def lifecycle_client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """Wire in-memory auth + stubs; disable Redis-backed security middleware."""

    import fakeredis.aioredis

    import app.infrastructure.redis as redis_module
    from app.api import captcha as captcha_api

    fake_redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr(redis_module, "get_security_redis_client", lambda: fake_redis)
    monkeypatch.setattr(redis_module, "get_redis_client", lambda: fake_redis)

    settings = get_settings()
    monkeypatch.setattr(settings, "security_suspicious_middleware_enabled", False)
    monkeypatch.setattr(settings, "security_input_sanitization_enabled", False)
    monkeypatch.setattr(settings, "security_behavioral_rate_enabled", False)
    monkeypatch.setattr(settings, "dead_mans_switch_enabled", False)
    monkeypatch.setattr(settings, "cloudflare_enabled", False)
    monkeypatch.setattr(settings, "cloudflare_enforce_edge", False)

    async def _skip_behavioral(*_args: Any, **_kwargs: Any) -> None:
        return None

    monkeypatch.setattr(
        captcha_api, "enforce_generation_behavioral_limit", _skip_behavioral
    )

    repo = InMemoryAuthRepository()
    auth_service = AuthService(repo)
    payments = _FakePayments(daily_bonus_coins=1)
    ab_service = AbTestService(
        repository=object(),  # type: ignore[arg-type]
        model_name="test-model",
        redis_stage_ttl_seconds=60,
    )
    analytics_service = StyleAnalyticsService(_EmptyStyleRepo())
    bearer = HTTPBearer(auto_error=False)

    async def _auth_dep() -> AuthService:
        return auth_service

    async def override_get_current_user(
        credentials: HTTPAuthorizationCredentials | None = Security(bearer),
    ) -> User:
        from fastapi import HTTPException, status

        if credentials is None or credentials.scheme.lower() != "bearer":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing bearer access token.",
                headers={"WWW-Authenticate": "Bearer"},
            )
        try:
            payload = decode_and_validate_token(
                credentials.credentials, expected_type="access"
            )
        except InvalidTokenError as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired access token.",
                headers={"WWW-Authenticate": "Bearer"},
            ) from exc
        subject = str(payload.get("sub") or "").strip()
        try:
            user_id = UUID(subject)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token subject is not a valid user id.",
            ) from exc
        user = await repo.get_by_id(user_id)
        if user is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User not found for this token.",
            )
        if user.is_banned:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="User is banned for abuse.",
            )
        return user

    async def billing_access(
        current_user: User = Depends(override_get_current_user),
    ) -> User:
        return current_user

    async def override_payments() -> _FakePayments:
        return payments

    async def override_ab() -> AbTestService:
        return ab_service

    async def override_analytics() -> StyleAnalyticsService:
        return analytics_service

    app.dependency_overrides[auth_api.get_auth_service] = _auth_dep
    app.dependency_overrides[payments_api.get_current_user] = override_get_current_user
    app.dependency_overrides[payments_api.require_billing_access] = billing_access
    app.dependency_overrides[payments_api.get_payment_application_service] = (
        override_payments
    )
    app.dependency_overrides[ab_tests_api._get_service] = override_ab
    app.dependency_overrides[analytics_api.get_style_analytics_service] = (
        override_analytics
    )

    client = TestClient(app)
    try:
        yield client
    finally:
        app.dependency_overrides.clear()


def test_user_lifecycle_auth_profile_balance_ab_analytics(
    lifecycle_client: TestClient,
) -> None:
    email = f"lifecycle-{uuid4().hex[:10]}@example.com"
    password = "SecurePass1!"

    register = lifecycle_client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": password},
    )
    assert register.status_code == 201, register.text
    body = register.json()
    assert body["user"]["email"] == email
    assert body["user"]["ai_coins"] == 5
    assert body["tokens"]["access_token"]

    login = lifecycle_client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
    )
    assert login.status_code == 200, login.text
    access = login.json()["tokens"]["access_token"]
    headers = {"Authorization": f"Bearer {access}"}

    me = lifecycle_client.get("/api/v1/auth/me", headers=headers)
    assert me.status_code == 200, me.text
    assert me.json()["email"] == email
    assert me.json()["ai_coins"] == 5

    balance = lifecycle_client.get("/api/v1/payments/balance", headers=headers)
    assert balance.status_code == 200, balance.text
    assert balance.json()["ai_coins"] == 5
    assert balance.json()["daily_bonus_available"] is True

    generation = lifecycle_client.post("/api/v1/generations", headers=headers)
    assert generation.status_code in {400, 422}, generation.text
    assert generation.status_code != 500

    ab_preview = lifecycle_client.post(
        "/api/v1/ab-tests/preview",
        headers=headers,
        json={
            "product": {
                "sku": "SKU-1",
                "title": "Крем для лица 50 мл",
                "niche_key": "beauty-cream",
                "marketplace": "wildberries",
                "category": "beauty",
                "key_benefits": ["увлажнение"],
                "pain_points": ["сухая кожа"],
            }
        },
    )
    assert ab_preview.status_code == 200, ab_preview.text
    assert len(ab_preview.json()) == 3

    analytics = lifecycle_client.get(
        "/api/v1/analytics/style-presets",
        headers=headers,
    )
    assert analytics.status_code == 200, analytics.text
    assert analytics.json()["total_selections"] == 0
    assert "top_presets" in analytics.json()


def test_negative_auth_and_validation_do_not_500(
    lifecycle_client: TestClient,
) -> None:
    for path in (
        "/api/v1/auth/me",
        "/api/v1/payments/balance",
        "/api/v1/analytics/style-presets",
        "/api/v1/generations/history",
    ):
        response = lifecycle_client.get(path)
        assert response.status_code == 401, (path, response.text)

    bad_register = lifecycle_client.post(
        "/api/v1/auth/register",
        json={"email": "not-an-email", "password": "short"},
    )
    assert bad_register.status_code == 422, bad_register.text

    email = f"neg-{uuid4().hex[:10]}@example.com"
    created = lifecycle_client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "SecurePass1!"},
    )
    assert created.status_code == 201

    bad_login = lifecycle_client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "wrong-password"},
    )
    assert bad_login.status_code == 401, bad_login.text

    dup = lifecycle_client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "SecurePass1!"},
    )
    assert dup.status_code == 409, dup.text

    token = created.json()["tokens"]["access_token"]
    bad_ab = lifecycle_client.post(
        "/api/v1/ab-tests/preview",
        headers={"Authorization": f"Bearer {token}"},
        json={"product": {"sku": "x"}},
    )
    assert bad_ab.status_code == 422, bad_ab.text
