"""Unit tests for signup trial anti-abuse domain + AuthService trial path."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from app.application.auth_service import (
    AuthDisposableEmailError,
    AuthService,
)
from app.domain.auth import RegisterCommand
from app.domain.disposable_email import is_disposable_email
from app.domain.referral import generate_referral_code
from app.domain.signup_trial import (
    SignupAbuseContext,
    TrialDenialReason,
    compute_device_fingerprint_hash,
    decide_trial_after_checks,
    ipv4_subnet_24,
)
from app.models.enums import SubscriptionStatus
from app.models.user import User


def test_disposable_email_domains() -> None:
    assert is_disposable_email("abuser@guerrillamail.com")
    assert is_disposable_email("x@mail.guerrillamail.com")
    assert is_disposable_email("a@temp-mail.org")
    assert is_disposable_email("a@10minutemail.com")
    assert not is_disposable_email("user@gmail.com")
    assert not is_disposable_email("owner@company.ru")


def test_fingerprint_hash_stable_and_sensitive() -> None:
    a = compute_device_fingerprint_hash(
        device_fingerprint="dev-1",
        user_agent="Mozilla/5.0",
        accept_language="ru-RU",
    )
    b = compute_device_fingerprint_hash(
        device_fingerprint="dev-1",
        user_agent="Mozilla/5.0",
        accept_language="ru-RU",
    )
    c = compute_device_fingerprint_hash(
        device_fingerprint="dev-2",
        user_agent="Mozilla/5.0",
        accept_language="ru-RU",
    )
    assert a == b
    assert a != c
    assert len(a) == 64


def test_ipv4_subnet_24() -> None:
    assert ipv4_subnet_24("192.168.1.42") == "192.168.1.0/24"
    assert ipv4_subnet_24("10.0.5.200") == "10.0.5.0/24"
    assert ipv4_subnet_24("unknown") is None
    assert ipv4_subnet_24("not-an-ip") is None


def test_decide_trial_gates() -> None:
    granted = decide_trial_after_checks(
        fingerprint_hash="abc",
        fingerprint_exhausted=False,
        subnet="1.2.3.0/24",
        subnet_registration_count=2,
        subnet_max_accounts=3,
        is_proxy_or_vpn=False,
        device_fingerprint_present=True,
    )
    assert granted.granted is True

    exhausted = decide_trial_after_checks(
        fingerprint_hash="abc",
        fingerprint_exhausted=True,
        subnet="1.2.3.0/24",
        subnet_registration_count=1,
        subnet_max_accounts=3,
        is_proxy_or_vpn=False,
        device_fingerprint_present=True,
    )
    assert exhausted.denial_reason == TrialDenialReason.FINGERPRINT_EXHAUSTED

    subnet = decide_trial_after_checks(
        fingerprint_hash="abc",
        fingerprint_exhausted=False,
        subnet="1.2.3.0/24",
        subnet_registration_count=4,
        subnet_max_accounts=3,
        is_proxy_or_vpn=False,
        device_fingerprint_present=True,
    )
    assert subnet.denial_reason == TrialDenialReason.SUBNET_LIMIT

    proxy = decide_trial_after_checks(
        fingerprint_hash="abc",
        fingerprint_exhausted=False,
        subnet="1.2.3.0/24",
        subnet_registration_count=1,
        subnet_max_accounts=3,
        is_proxy_or_vpn=True,
        device_fingerprint_present=True,
    )
    assert proxy.denial_reason == TrialDenialReason.PROXY_OR_VPN

    missing = decide_trial_after_checks(
        fingerprint_hash=None,
        fingerprint_exhausted=False,
        subnet=None,
        subnet_registration_count=0,
        subnet_max_accounts=3,
        is_proxy_or_vpn=False,
        device_fingerprint_present=False,
    )
    assert missing.denial_reason == TrialDenialReason.MISSING_DEVICE_FINGERPRINT


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
            is_flagged=False,
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


class _Wallet:
    def __init__(self, repo: _Repo) -> None:
        self.repo = repo
        self.credits: list[tuple[UUID, int]] = []

    async def debit_coins(self, *, user_id: UUID, amount: int) -> int:
        raise NotImplementedError

    async def refund_coins(self, *, user_id: UUID, amount: int) -> int:
        raise NotImplementedError

    async def credit_coins(self, *, user_id: UUID, amount: int) -> int:
        user = self.repo.by_id[user_id]
        user.ai_coins = int(user.ai_coins) + amount
        self.credits.append((user_id, amount))
        return int(user.ai_coins)


class _TrialStore:
    def __init__(self) -> None:
        self.exhausted: set[str] = set()
        self.seen: set[str] = set()
        self.subnets: dict[str, int] = {}

    async def is_fingerprint_exhausted(self, *, fingerprint_hash: str) -> bool:
        return fingerprint_hash in self.exhausted

    async def remember_fingerprint(
        self,
        *,
        fingerprint_hash: str,
        ttl_seconds: int,
    ) -> None:
        if fingerprint_hash not in self.exhausted:
            self.seen.add(fingerprint_hash)

    async def mark_fingerprint_exhausted(
        self,
        *,
        fingerprint_hash: str,
        ttl_seconds: int,
    ) -> None:
        self.exhausted.add(fingerprint_hash)
        self.seen.discard(fingerprint_hash)

    async def increment_subnet_registrations(
        self,
        *,
        subnet: str,
        ttl_seconds: int,
    ) -> int:
        self.subnets[subnet] = self.subnets.get(subnet, 0) + 1
        return self.subnets[subnet]


class _TrialClaims:
    def __init__(self) -> None:
        self.rows: list[dict] = []

    async def has_granted_trial(self, *, fingerprint_hash: str) -> bool:
        return any(
            r["fingerprint_hash"] == fingerprint_hash and r["trial_granted"]
            for r in self.rows
        )

    async def record_claim(self, **kwargs) -> None:
        self.rows.append(kwargs)


class _Proxy:
    def __init__(self, flag: bool = False) -> None:
        self.flag = flag

    async def is_proxy_or_vpn(self, *, ip: str) -> bool:
        return self.flag


class _SilentBanStore:
    def __init__(self) -> None:
        self.flagged_ips: set[str] = set()

    async def mark_flagged_ip(self, *, ip: str, ttl_seconds: int) -> None:
        self.flagged_ips.add(ip)

    async def is_flagged_ip(self, *, ip: str) -> bool:
        return ip in self.flagged_ips


def _ctx(**overrides) -> SignupAbuseContext:
    base = dict(
        client_ip="203.0.113.10",
        user_agent="Mozilla/5.0 Test",
        accept_language="ru-RU,ru;q=0.9",
        device_fingerprint="fp-device-abc",
    )
    base.update(overrides)
    return SignupAbuseContext(**base)


def _build_service(
    *,
    proxy: bool = False,
    store: _TrialStore | None = None,
    claims: _TrialClaims | None = None,
) -> tuple[AuthService, _Repo, _Wallet, _TrialStore, _TrialClaims, _SilentBanStore]:
    repo = _Repo()
    wallet = _Wallet(repo)
    trial_store = store or _TrialStore()
    trial_claims = claims or _TrialClaims()
    silent_ban = _SilentBanStore()
    service = AuthService(
        repo,
        coin_wallet=wallet,
        trial_store=trial_store,
        trial_claims=trial_claims,
        proxy_detector=_Proxy(proxy),
        silent_ban_store=silent_ban,
        trial_coins=5,
        subnet_max_accounts=3,
    )
    return service, repo, wallet, trial_store, trial_claims, silent_ban


@pytest.mark.asyncio
async def test_register_rejects_disposable_email() -> None:
    service, *_ = _build_service()
    with pytest.raises(AuthDisposableEmailError, match="временных почт"):
        await service.register(
            RegisterCommand(email="spam@yopmail.com", password="SecurePass1!"),
            abuse_context=_ctx(),
        )


@pytest.mark.asyncio
async def test_register_grants_trial_when_clean() -> None:
    service, repo, wallet, store, claims, silent_ban = _build_service()
    view, _tokens = await service.register(
        RegisterCommand(email="ok@example.com", password="SecurePass1!"),
        abuse_context=_ctx(),
    )
    assert view.ai_coins == 5
    assert len(wallet.credits) == 1
    assert store.exhausted
    assert claims.rows[-1]["trial_granted"] is True
    user = next(iter(repo.by_id.values()))
    assert user.is_flagged is False
    assert silent_ban.flagged_ips == set()


@pytest.mark.asyncio
async def test_register_denies_trial_on_exhausted_fingerprint() -> None:
    service, repo, wallet, store, claims, silent_ban = _build_service()
    fp_hash = compute_device_fingerprint_hash(
        device_fingerprint="fp-device-abc",
        user_agent="Mozilla/5.0 Test",
        accept_language="ru-RU,ru;q=0.9",
    )
    store.exhausted.add(fp_hash)

    view, _ = await service.register(
        RegisterCommand(email="second@example.com", password="SecurePass1!"),
        abuse_context=_ctx(),
    )
    assert view.ai_coins == 0
    assert wallet.credits == []
    assert claims.rows[-1]["denial_reason"] == TrialDenialReason.FINGERPRINT_EXHAUSTED
    user = next(iter(repo.by_id.values()))
    assert user.is_flagged is True
    assert user.flag_reason == "fingerprint_duplicate"
    assert "203.0.113.10" in silent_ban.flagged_ips


@pytest.mark.asyncio
async def test_register_denies_trial_on_subnet_overflow() -> None:
    store = _TrialStore()
    store.subnets["203.0.113.0/24"] = 3  # next incr → 4 > 3
    service, repo, wallet, _store, claims, silent_ban = _build_service(store=store)

    view, _ = await service.register(
        RegisterCommand(email="fourth@example.com", password="SecurePass1!"),
        abuse_context=_ctx(client_ip="203.0.113.55"),
    )
    assert view.ai_coins == 0
    assert wallet.credits == []
    assert claims.rows[-1]["denial_reason"] == TrialDenialReason.SUBNET_LIMIT
    user = next(iter(repo.by_id.values()))
    assert user.is_flagged is True
    assert user.flag_reason == "subnet_duplicate"
    assert "203.0.113.55" in silent_ban.flagged_ips


@pytest.mark.asyncio
async def test_register_denies_trial_on_proxy() -> None:
    service, repo, wallet, _store, claims, silent_ban = _build_service(proxy=True)
    view, _ = await service.register(
        RegisterCommand(email="vpn@example.com", password="SecurePass1!"),
        abuse_context=_ctx(),
    )
    assert view.ai_coins == 0
    assert wallet.credits == []
    assert claims.rows[-1]["denial_reason"] == TrialDenialReason.PROXY_OR_VPN
    user = next(iter(repo.by_id.values()))
    assert user.is_flagged is False
    assert silent_ban.flagged_ips == set()


@pytest.mark.asyncio
async def test_register_denies_trial_without_device_fingerprint() -> None:
    service, repo, wallet, _store, claims, silent_ban = _build_service()
    view, _ = await service.register(
        RegisterCommand(email="nofp@example.com", password="SecurePass1!"),
        abuse_context=_ctx(device_fingerprint=""),
    )
    assert view.ai_coins == 0
    assert wallet.credits == []
    assert claims.rows[-1]["denial_reason"] == TrialDenialReason.MISSING_DEVICE_FINGERPRINT
    user = next(iter(repo.by_id.values()))
    assert user.is_flagged is False
    assert silent_ban.flagged_ips == set()
