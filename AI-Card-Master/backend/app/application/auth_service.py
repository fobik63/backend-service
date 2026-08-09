"""Application service: user registration and JWT login."""

from __future__ import annotations

import logging
from uuid import UUID

from app.application.ports.auth import AuthRepositoryPort
from app.application.ports.coin_wallet import CoinWalletPort
from app.application.ports.signup_trial import (
    ProxyDetectorPort,
    SignupTrialClaimRepositoryPort,
    SignupTrialStorePort,
    SignupTrialStoreUnavailableError,
)
from app.application.ports.silent_ban import (
    SilentBanStorePort,
    SilentBanStoreUnavailableError,
)
from app.application.ports.unit_of_work import UnitOfWorkPort
from app.core.security import (
    decode_and_validate_token,
    hash_password,
    verify_password,
)
from app.domain.auth import (
    AuthTokens,
    AuthUserView,
    LoginCommand,
    OtpRequestCommand,
    OtpVerifyCommand,
    RegisterCommand,
)
from app.domain.disposable_email import is_disposable_email
from app.domain.referral import generate_referral_code
from app.domain.signup_trial import (
    SignupAbuseContext,
    TrialDenialReason,
    TrialGrantDecision,
    compute_device_fingerprint_hash,
    decide_trial_after_checks,
    ipv4_subnet_24,
)
from app.domain.silent_ban import flag_reason_for, should_silent_flag
from app.models.user import User
from app.services.auth import (
    FAMILY_REUSE_DETAIL,
    InvalidRefreshTokenError,
    RefreshTokenRotationService,
    TokenFamilyRevokedError,
    TokenRotationStoreError,
    get_refresh_token_rotation_service,
)

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


class AuthRegistrationBlockedError(AuthError):
    """Hard anti-abuse block: fingerprint or /24 subnet already exhausted."""

    def __init__(
        self,
        message: str = (
            "Регистрация с этого устройства или сети недоступна. "
            "Смените устройство или сеть и попробуйте снова."
        ),
    ) -> None:
        super().__init__(message)


class AuthRefreshError(AuthError):
    """Refresh token is invalid or expired."""


class AuthTokenFamilyRevokedError(AuthError):
    """Refresh reuse detected — token family burned."""

    def __init__(self, message: str = FAMILY_REUSE_DETAIL) -> None:
        super().__init__(message)


class AuthTokenStoreError(AuthError):
    """RTR security store (Redis) unavailable."""


class AuthOtpError(AuthError):
    """OTP request or verification failed."""


class AuthOtpStoreError(AuthError):
    """OTP Redis store unavailable."""


class AuthTelegramError(AuthError):
    """Telegram Login Widget authentication failed."""


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
        token_rotation: RefreshTokenRotationService | None = None,
        unit_of_work: UnitOfWorkPort | None = None,
        otp_store: object | None = None,
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
        self._token_rotation = token_rotation or get_refresh_token_rotation_service()
        self._unit_of_work = unit_of_work
        self._otp_store = otp_store
        self._trial_coins = max(0, int(trial_coins))
        self._subnet_max_accounts = max(1, int(subnet_max_accounts))
        self._subnet_ttl_seconds = max(60, int(subnet_ttl_seconds))
        self._fingerprint_ttl_seconds = max(0, int(fingerprint_ttl_seconds))
        self._flagged_ip_ttl_seconds = max(0, int(flagged_ip_ttl_seconds))
        self._trial_enabled = trial_enabled

    async def _commit_unit_of_work(self) -> None:
        if self._unit_of_work is None:
            return
        try:
            await self._unit_of_work.commit()
        except Exception:
            await self._unit_of_work.rollback()
            raise

    def _issue_tokens(self, user_id: UUID) -> AuthTokens:
        """Issue a new token family (login / register)."""

        return self._token_rotation.issue_token_pair(user_id)

    @staticmethod
    def _compute_fingerprint_hash(
        context: SignupAbuseContext,
    ) -> str | None:
        device_fp = context.device_fingerprint.strip()
        if not device_fp:
            return None
        return compute_device_fingerprint_hash(
            device_fingerprint=device_fp,
            user_agent=context.user_agent,
            accept_language=context.accept_language,
        )

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

        fingerprint_hash: str | None = None
        if abuse_context is not None:
            fingerprint_hash = self._compute_fingerprint_hash(abuse_context)
            if (
                self._trial_store is not None
                and self._trial_claims is not None
            ):
                await self._assert_registration_allowed(
                    fingerprint_hash=fingerprint_hash,
                    context=abuse_context,
                )

        user = await self._repository.create_user(
            email=command.email,
            hashed_password=hash_password(command.password),
            fingerprint_hash=fingerprint_hash,
        )
        if fingerprint_hash is not None:
            # Explicit Postgres persistence (create_user also sets the column).
            user.fingerprint_hash = fingerprint_hash
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

        await self._commit_unit_of_work()
        return _to_view(user), self._issue_tokens(user.id)

    async def login(
        self,
        command: LoginCommand,
        *,
        abuse_context: SignupAbuseContext | None = None,
    ) -> tuple[AuthUserView, AuthTokens]:
        user = await self._repository.get_by_email(command.email)
        if user is None or not verify_password(command.password, user.hashed_password):
            raise AuthCredentialsError("Invalid email or password.")
        if user.is_banned:
            raise AuthCredentialsError("User is banned for abuse.")

        if abuse_context is not None:
            fingerprint_hash = self._compute_fingerprint_hash(abuse_context)
            if fingerprint_hash is not None:
                updated = await self._repository.update_fingerprint_hash(
                    user.id,
                    fingerprint_hash=fingerprint_hash,
                )
                if updated is not None:
                    user = updated

        await self._commit_unit_of_work()
        return _to_view(user), self._issue_tokens(user.id)

    async def _assert_registration_allowed(
        self,
        *,
        fingerprint_hash: str | None,
        context: SignupAbuseContext,
    ) -> None:
        """Hard-block registration when device or /24 subnet already exceeded limits.

        Checks durable Postgres (``users.fingerprint_hash``, ``signup_trial_claims``)
        plus Redis counters. Fail-closed when the security store is unavailable.
        """

        assert self._trial_store is not None
        assert self._trial_claims is not None

        subnet = ipv4_subnet_24(context.client_ip)

        try:
            if fingerprint_hash is not None:
                if await self._repository.exists_fingerprint_hash(
                    fingerprint_hash=fingerprint_hash
                ):
                    raise AuthRegistrationBlockedError()
                if await self._trial_claims.has_fingerprint(
                    fingerprint_hash=fingerprint_hash
                ):
                    raise AuthRegistrationBlockedError()
                if await self._trial_claims.has_granted_trial(
                    fingerprint_hash=fingerprint_hash
                ):
                    raise AuthRegistrationBlockedError()
                if await self._trial_store.is_fingerprint_exhausted(
                    fingerprint_hash=fingerprint_hash
                ):
                    raise AuthRegistrationBlockedError()

            if subnet is not None:
                redis_count = await self._trial_store.get_subnet_registrations(
                    subnet=subnet
                )
                pg_count = await self._trial_claims.count_accounts_for_subnet(
                    subnet=subnet
                )
                if (
                    redis_count >= self._subnet_max_accounts
                    or pg_count >= self._subnet_max_accounts
                ):
                    raise AuthRegistrationBlockedError()
        except AuthRegistrationBlockedError:
            raise
        except SignupTrialStoreUnavailableError as exc:
            logger.warning(
                "Signup trial store unavailable during registration hard-block; deny"
            )
            raise AuthRegistrationBlockedError() from exc

    async def refresh(self, refresh_token: str) -> tuple[AuthUserView, AuthTokens]:
        """Rotate a refresh token (RTR) and return the authenticated user + new pair."""

        try:
            tokens = await self._token_rotation.rotate(refresh_token)
        except TokenFamilyRevokedError as exc:
            raise AuthTokenFamilyRevokedError(str(exc)) from exc
        except InvalidRefreshTokenError as exc:
            raise AuthRefreshError(str(exc)) from exc
        except TokenRotationStoreError as exc:
            raise AuthTokenStoreError(str(exc)) from exc

        payload = decode_and_validate_token(tokens.access_token, expected_type="access")
        subject = str(payload.get("sub") or "").strip()
        try:
            user_id = UUID(subject)
        except ValueError as exc:
            raise AuthRefreshError("Rotated token subject is invalid.") from exc

        user = await self._repository.get_by_id(user_id)
        if user is None:
            raise AuthNotFoundError("User not found.")
        if user.is_banned:
            raise AuthCredentialsError("User is banned for abuse.")
        await self._commit_unit_of_work()
        return _to_view(user), tokens

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
        fingerprint_hash = self._compute_fingerprint_hash(context)

        # Keep Postgres profile in sync even if create_user omitted the column.
        if fingerprint_hash is not None and user.fingerprint_hash != fingerprint_hash:
            try:
                updated = await self._repository.update_fingerprint_hash(
                    user.id,
                    fingerprint_hash=fingerprint_hash,
                )
                if updated is not None:
                    user.fingerprint_hash = updated.fingerprint_hash
            except Exception:
                logger.exception(
                    "Failed to persist fingerprint_hash for user %s",
                    user.id,
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
                if not fingerprint_exhausted:
                    fingerprint_exhausted = await self._trial_claims.has_fingerprint(
                        fingerprint_hash=fingerprint_hash
                    )
                if not fingerprint_exhausted:
                    fingerprint_exhausted = (
                        await self._repository.exists_fingerprint_hash(
                            fingerprint_hash=fingerprint_hash,
                            exclude_user_id=user.id,
                        )
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

    async def request_otp(self, command: OtpRequestCommand) -> tuple[str, int]:
        """Issue a fresh OTP and return ``(plain_code, ttl_seconds)``.

        The plain code must be delivered out-of-band (email BackgroundTask).
        Never include it in an HTTP response body in production.
        """

        if is_disposable_email(command.email):
            raise AuthDisposableEmailError(
                "Использование временных почт запрещено"
            )
        if self._otp_store is None:
            raise AuthOtpStoreError("OTP store is not configured.")

        from app.infrastructure.security.otp_store import (
            OtpStoreUnavailableError,
        )

        try:
            issued = await self._otp_store.issue(command.email)  # type: ignore[union-attr]
        except OtpStoreUnavailableError as exc:
            raise AuthOtpStoreError(str(exc)) from exc
        return issued.code, int(issued.ttl_seconds)

    async def verify_otp(
        self,
        command: OtpVerifyCommand,
        *,
        abuse_context: SignupAbuseContext | None = None,
    ) -> tuple[AuthUserView, AuthTokens]:
        """Verify OTP and return a session (creates account on first success)."""

        if is_disposable_email(command.email):
            raise AuthDisposableEmailError(
                "Использование временных почт запрещено"
            )
        if self._otp_store is None:
            raise AuthOtpStoreError("OTP store is not configured.")

        from app.infrastructure.security.otp_store import (
            OtpStoreUnavailableError,
        )

        try:
            ok = await self._otp_store.verify_and_consume(  # type: ignore[union-attr]
                command.email,
                command.code,
            )
        except OtpStoreUnavailableError as exc:
            raise AuthOtpStoreError(str(exc)) from exc
        if not ok:
            raise AuthOtpError("Неверный или просроченный код")

        user = await self._repository.get_by_email(command.email)
        if user is None:
            import secrets

            fingerprint_hash: str | None = None
            if abuse_context is not None:
                fingerprint_hash = self._compute_fingerprint_hash(abuse_context)
                if (
                    self._trial_store is not None
                    and self._trial_claims is not None
                ):
                    await self._assert_registration_allowed(
                        fingerprint_hash=fingerprint_hash,
                        context=abuse_context,
                    )
            user = await self._repository.create_user(
                email=command.email,
                hashed_password=hash_password(secrets.token_urlsafe(48)),
                fingerprint_hash=fingerprint_hash,
            )
            if (
                self._trial_enabled
                and self._trial_coins > 0
                and abuse_context is not None
                and self._coin_wallet is not None
                and self._trial_store is not None
                and self._trial_claims is not None
                and self._proxy_detector is not None
            ):
                await self._maybe_grant_signup_trial(
                    user=user,
                    context=abuse_context,
                )
                refreshed = await self._repository.get_by_id(user.id)
                if refreshed is not None:
                    user = refreshed
        elif user.is_banned:
            raise AuthCredentialsError("User is banned for abuse.")

        await self._commit_unit_of_work()
        return _to_view(user), self._issue_tokens(user.id)

    async def change_password(
        self,
        user_id: UUID,
        *,
        current_password: str,
        new_password: str,
    ) -> None:
        """Verify the current password and replace it with a new Argon2 hash."""

        user = await self._repository.get_by_id(user_id)
        if user is None:
            raise AuthNotFoundError("User not found.")
        if user.is_banned:
            raise AuthCredentialsError("User is banned for abuse.")
        if not verify_password(current_password, user.hashed_password):
            raise AuthCredentialsError("Current password is incorrect.")
        cleaned = (new_password or "").strip()
        if len(cleaned) < 8:
            raise AuthCredentialsError("New password must be at least 8 characters.")
        if cleaned == current_password:
            raise AuthCredentialsError(
                "New password must be different from the current password."
            )
        updated = await self._repository.update_password(
            user_id,
            hashed_password=hash_password(cleaned),
        )
        if updated is None:
            raise AuthNotFoundError("User not found.")
        await self._commit_unit_of_work()

    async def login_with_telegram(
        self,
        *,
        telegram_id: int,
        username: str | None = None,
        first_name: str | None = None,
        abuse_context: SignupAbuseContext | None = None,
    ) -> tuple[AuthUserView, AuthTokens]:
        """Authenticate (or provision) a user from a verified Telegram payload."""

        user = await self._repository.get_by_telegram_id(telegram_id)
        if user is None:
            import secrets

            # Stable synthetic mailbox — unique + not disposable.
            handle = (username or first_name or "user").strip().lower()
            safe = "".join(ch for ch in handle if ch.isalnum() or ch in "._-")[:24]
            email = f"tg_{telegram_id}_{safe or 'user'}@telegram.local"

            fingerprint_hash: str | None = None
            if abuse_context is not None:
                fingerprint_hash = self._compute_fingerprint_hash(abuse_context)
                if (
                    self._trial_store is not None
                    and self._trial_claims is not None
                ):
                    await self._assert_registration_allowed(
                        fingerprint_hash=fingerprint_hash,
                        context=abuse_context,
                    )
            # Collision-safe: if synthetic email exists, just link telegram_id.
            existing_email = await self._repository.get_by_email(email)
            if existing_email is not None:
                linked = await self._repository.link_telegram_id(
                    existing_email.id,
                    telegram_id=telegram_id,
                )
                user = linked or existing_email
            else:
                user = await self._repository.create_user(
                    email=email,
                    hashed_password=hash_password(secrets.token_urlsafe(48)),
                    fingerprint_hash=fingerprint_hash,
                    telegram_id=telegram_id,
                )
                if (
                    self._trial_enabled
                    and self._trial_coins > 0
                    and abuse_context is not None
                    and self._coin_wallet is not None
                    and self._trial_store is not None
                    and self._trial_claims is not None
                    and self._proxy_detector is not None
                ):
                    await self._maybe_grant_signup_trial(
                        user=user,
                        context=abuse_context,
                    )
                    refreshed = await self._repository.get_by_id(user.id)
                    if refreshed is not None:
                        user = refreshed
        elif user.is_banned:
            raise AuthCredentialsError("User is banned for abuse.")

        await self._commit_unit_of_work()
        return _to_view(user), self._issue_tokens(user.id)
