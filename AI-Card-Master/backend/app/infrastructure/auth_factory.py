"""Composition root for auth HTTP façade."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.application.auth_service import AuthService
from app.core.config import get_settings
from app.infrastructure.persistence.auth_repository import AuthRepository
from app.infrastructure.persistence.coin_wallet import SqlAlchemyCoinWallet
from app.infrastructure.persistence.signup_trial_repository import (
    SignupTrialClaimRepository,
)
from app.infrastructure.security.otp_store import RedisOtpStore
from app.infrastructure.security.proxy_detector import AsyncProxyDetector
from app.infrastructure.security.silent_ban_store import RedisSilentBanStore
from app.infrastructure.security.signup_trial_store import RedisSignupTrialStore
from app.infrastructure.security.token_family_store import RedisTokenFamilyStore
from app.services.auth import RefreshTokenRotationService


def build_auth_service(session: AsyncSession) -> AuthService:
    settings = get_settings()
    return AuthService(
        AuthRepository(session),
        coin_wallet=SqlAlchemyCoinWallet(session),
        trial_store=RedisSignupTrialStore(),
        trial_claims=SignupTrialClaimRepository(session),
        proxy_detector=AsyncProxyDetector(
            enabled=settings.signup_trial_proxy_check_enabled,
            use_ip_api=settings.signup_trial_ip_api_enabled,
            timeout_seconds=settings.signup_trial_proxy_timeout_seconds,
        ),
        silent_ban_store=RedisSilentBanStore(),
        token_rotation=RefreshTokenRotationService(store=RedisTokenFamilyStore()),
        otp_store=RedisOtpStore(
            ttl_seconds=settings.otp_ttl_seconds,
            code_length=settings.otp_code_length,
        ),
        trial_coins=settings.signup_trial_coins,
        subnet_max_accounts=settings.signup_trial_subnet_max_accounts,
        subnet_ttl_seconds=settings.signup_trial_subnet_ttl_seconds,
        fingerprint_ttl_seconds=settings.signup_trial_fingerprint_ttl_seconds,
        flagged_ip_ttl_seconds=settings.silent_ban_flagged_ip_ttl_seconds,
        trial_enabled=settings.signup_trial_enabled,
    )
