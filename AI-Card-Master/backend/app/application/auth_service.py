"""Application service: user registration and JWT login."""

from __future__ import annotations

import logging
from uuid import UUID

from app.application.ports.auth import AuthRepositoryPort
from app.application.ports.coin_wallet import CoinWalletPort
from app.application.ports.silent_ban import (
    SilentBanStorePort,
    SilentBanStoreUnavailableError,
)
from app.application.ports.signup_trial import (
    ProxyDetectorPort,
    SignupTrialClaimRepositoryPort,
    SignupTrialStorePort,
    SignupTrialStoreUnavailableError,
)
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
from app.domain.disposable_email import is_disposable_email
from app.domain.referral import generate_referral_code
from app.domain.silent_ban import flag_reason_for, should_silent_flag
from app.domain.signup_trial import (
    SignupAbuseContext,
    TrialDenialReason,
    TrialGrantDecision,
    compute_device_fingerprint_hash,
    decide_trial_after_checks,
    ipv4_subnet_24,
)
from app.models.user import User

logger = logging.getLogger(__name__)


class AuthError(Exception):
    """Base auth use-case error."""


class AuthConflictError(AuthError):
    """Email already registered."""


class AuthCredentialsError(AuthError):
    """Invalid email/password or banned account."""


class AuthNotFoundError(AuthError):
    """Authenticated subject no longer exists."""


class AuthDisposableEmailError(AuthError):
    """Temporary / disposable mailbox domains are not allowed."""


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

    def __init__(
        self,
        repository: AuthRepositoryPort,
        *,
        coin_wallet: CoinWalletPort | None = None,
        trial_store: SignupTrialStorePort | None = None,
        trial_claims: SignupTrialClaimRepositoryPort | None = None,
        proxy_detector: ProxyDetectorPort | None = None,
        silent_ban_store: SilentBanStorePort | None = None,
        trial_coins: int = 5,
        subnet_max_accounts: int = 3,
        subnet_ttl_seconds: int = 86_400,
        fingerprint_ttl_seconds: int = 90 * 24 * 3600,
        flagged_ip_ttl_seconds: int = 90 * 24 * 3600,
        trial_enabled: bool = True,
    ) -> None:
        self._repository = repository
        self._coin_wallet = coin_wallet
        self._trial_store = trial_store
        self._trial_claims = trial_claims
        self._proxy_detector = proxy_detector
        self._silent_ban_store = silent_ban_store
        self._trial_coins = max(0, int(trial_coins))
        self._subnet_max_accounts = max(1, int(subnet_max_accounts))
        self._subnet_ttl_seconds = max(60, int(subnet_ttl_seconds))
        self._fingerprint_ttl_seconds = max(0, int(fingerprint_ttl_seconds))
        self._flagged_ip_ttl_seconds = max(0, int(flagged_ip_ttl_seconds))
        self._trial_enabled = trial_enabled

    async def register(
        self,
        command: RegisterCommand,
        *,
        abuse_context: SignupAbuseContext | None = None,
    ) -> tuple[AuthUserView, AuthTokens]:
        if is_disposable_email(command.email):
            raise AuthDisposableEmailError(
                "Использование временных почт запрещено"
            )

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

        if (
            self._trial_enabled
            and self._trial_coins > 0
            and abuse_context is not None
            and self._coin_wallet is not None
            and self._trial_store is not None
            and self._trial_claims is not None
            and self._proxy_detector is not None
        ):
            await self._maybe_grant_signup_trial(user=user, context=abuse_context)
            refreshed = await self._repository.get_by_id(user.id)
            if refreshed is not None:
                user = refreshed

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

    async def _maybe_grant_signup_trial(
        self,
        *,
        user: User,
        context: SignupAbuseContext,
    ) -> TrialGrantDecision:
        """Evaluate multi-layer anti-abuse and credit trial coins when allowed."""

        assert self._trial_store is not None
        assert self._trial_claims is not None
        assert self._proxy_detector is not None
        assert self._coin_wallet is not None

        device_fp = context.device_fingerprint.strip()
        fingerprint_hash: str | None = None
        if device_fp:
            fingerprint_hash = compute_device_fingerprint_hash(
                device_fingerprint=device_fp,
                user_agent=context.user_agent,
                accept_language=context.accept_language,
            )

        subnet = ipv4_subnet_24(context.client_ip)
        subnet_count = 0
        fingerprint_exhausted = False
        is_proxy = False

        try:
            if subnet is not None:
                subnet_count = await self._trial_store.increment_subnet_registrations(
                    subnet=subnet,
                    ttl_seconds=self._subnet_ttl_seconds,
                )
            if fingerprint_hash is not None:
                fingerprint_exhausted = await self._trial_store.is_fingerprint_exhausted(
                    fingerprint_hash=fingerprint_hash
                )
                if not fingerprint_exhausted:
                    fingerprint_exhausted = await self._trial_claims.has_granted_trial(
                        fingerprint_hash=fingerprint_hash
                    )
            is_proxy = await self._proxy_detector.is_proxy_or_vpn(ip=context.client_ip)
        except SignupTrialStoreUnavailableError:
            logger.warning(
                "Signup trial store unavailable; denying trial for user %s",
                user.id,
            )
            decision = TrialGrantDecision(
                granted=False,
                denial_reason=TrialDenialReason.STORE_UNAVAILABLE,
                fingerprint_hash=fingerprint_hash,
                ip_subnet=subnet,
            )
            await self._persist_claim(user=user, context=context, decision=decision)
            return decision

        decision = decide_trial_after_checks(
            fingerprint_hash=fingerprint_hash,
            fingerprint_exhausted=fingerprint_exhausted,
            subnet=subnet,
            subnet_registration_count=subnet_count,
            subnet_max_accounts=self._subnet_max_accounts,
            is_proxy_or_vpn=is_proxy,
            device_fingerprint_present=bool(device_fp),
        )

        if decision.granted and fingerprint_hash is not None:
            try:
                new_balance = await self._coin_wallet.credit_coins(
                    user_id=user.id,
                    amount=self._trial_coins,
                )
                user.ai_coins = new_balance
                await self._trial_store.mark_fingerprint_exhausted(
                    fingerprint_hash=fingerprint_hash,
                    ttl_seconds=self._fingerprint_ttl_seconds,
                )
                logger.info(
                    "Signup trial granted: user=%s coins=%s fp=%s…",
                    user.id,
                    self._trial_coins,
                    fingerprint_hash[:12],
                )
            except Exception:
                logger.exception(
                    "Failed to credit signup trial for user %s; recording denial",
                    user.id,
                )
                decision = TrialGrantDecision(
                    granted=False,
                    denial_reason=TrialDenialReason.STORE_UNAVAILABLE,
                    fingerprint_hash=fingerprint_hash,
                    ip_subnet=subnet,
                )
        else:
            if fingerprint_hash is not None:
                try:
                    await self._trial_store.remember_fingerprint(
                        fingerprint_hash=fingerprint_hash,
                        ttl_seconds=self._fingerprint_ttl_seconds,
                    )
                except SignupTrialStoreUnavailableError:
                    logger.warning(
                        "Could not remember fingerprint for user %s",
                        user.id,
                    )
            if not decision.granted:
                logger.info(
                    "Signup trial denied: user=%s reason=%s subnet=%s",
                    user.id,
                    decision.denial_reason,
                    subnet,
                )
                # Silent ban: fingerprint / subnet duplicates → flag, still 201.
                if should_silent_flag(decision.denial_reason):
                    await self._apply_silent_flag(
                        user=user,
                        denial_reason=decision.denial_reason,
                        client_ip=context.client_ip,
                    )

        await self._persist_claim(user=user, context=context, decision=decision)
        return decision

    async def _apply_silent_flag(
        self,
        *,
        user: User,
        denial_reason: TrialDenialReason | None,
        client_ip: str,
    ) -> None:
        """Mark the account + IP for silent restrictions; never raise to the client."""

        if denial_reason is None:
            return
        reason = flag_reason_for(denial_reason)
        try:
            flagged = await self._repository.flag_user(user.id, reason=reason)
            if flagged is not None:
                user.is_flagged = True
                user.flag_reason = flagged.flag_reason
                user.ai_coins = int(flagged.ai_coins or 0)
        except Exception:
            logger.exception("Failed to persist silent flag for user %s", user.id)
            return

        if self._silent_ban_store is None:
            return
        try:
            await self._silent_ban_store.mark_flagged_ip(
                ip=client_ip,
                ttl_seconds=self._flagged_ip_ttl_seconds,
            )
        except SilentBanStoreUnavailableError:
            logger.warning(
                "Silent-ban IP store unavailable for user %s; DB flag retained",
                user.id,
            )
        except Exception:
            logger.exception(
                "Unexpected error marking flagged IP for user %s",
                user.id,
            )

    async def _persist_claim(
        self,
        *,
        user: User,
        context: SignupAbuseContext,
        decision: TrialGrantDecision,
    ) -> None:
        assert self._trial_claims is not None
        try:
            await self._trial_claims.record_claim(
                user_id=user.id,
                fingerprint_hash=decision.fingerprint_hash,
                client_ip=context.client_ip,
                ip_subnet=decision.ip_subnet,
                trial_granted=decision.granted,
                denial_reason=decision.denial_reason,
                user_agent=context.user_agent,
                accept_language=context.accept_language,
            )
        except Exception:
            logger.exception(
                "Failed to persist signup trial claim for user %s",
                user.id,
            )
