"""Ports for signup trial anti-abuse (fingerprint, subnet, proxy)."""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from app.domain.signup_trial import TrialDenialReason


class SignupTrialStoreUnavailableError(RuntimeError):
    """Security Redis (or equivalent) is unavailable for trial anti-abuse checks."""


class SignupTrialStorePort(Protocol):
    """Redis-backed fingerprint exhaustion flags and /24 subnet counters."""

    async def is_fingerprint_exhausted(self, *, fingerprint_hash: str) -> bool:
        """Return True when this device hash already received a trial."""

        ...

    async def remember_fingerprint(
        self,
        *,
        fingerprint_hash: str,
        ttl_seconds: int,
    ) -> None:
        """Store the hash in Redis (without consuming the trial)."""

        ...

    async def mark_fingerprint_exhausted(
        self,
        *,
        fingerprint_hash: str,
        ttl_seconds: int,
    ) -> None:
        """Persist that the fingerprint has consumed its signup trial."""

        ...

    async def increment_subnet_registrations(
        self,
        *,
        subnet: str,
        ttl_seconds: int,
    ) -> int:
        """Atomically increment the subnet registration counter; return new count."""

        ...


class SignupTrialClaimRepositoryPort(Protocol):
    """Durable Postgres record of signup fingerprint / trial outcomes."""

    async def has_granted_trial(self, *, fingerprint_hash: str) -> bool:
        """Return True when any prior row granted a trial for this hash."""

        ...

    async def record_claim(
        self,
        *,
        user_id: UUID,
        fingerprint_hash: str | None,
        client_ip: str | None,
        ip_subnet: str | None,
        trial_granted: bool,
        denial_reason: TrialDenialReason | None,
        user_agent: str | None,
        accept_language: str | None,
    ) -> None:
        """Insert an audit row for this registration's trial decision."""

        ...


class ProxyDetectorPort(Protocol):
    """Lightweight async VPN / Proxy / Tor detection for a client IP."""

    async def is_proxy_or_vpn(self, *, ip: str) -> bool:
        """Return True when the IP looks like a proxy, VPN, Tor exit, or hosting relay."""

        ...
