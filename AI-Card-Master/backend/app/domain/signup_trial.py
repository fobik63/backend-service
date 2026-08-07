"""Signup trial grant rules and anti-abuse primitives (pure domain)."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import StrEnum
from ipaddress import IPv4Address, IPv6Address, ip_address, ip_network


class TrialDenialReason(StrEnum):
    """Why the automatic signup trial was not granted."""

    MISSING_DEVICE_FINGERPRINT = "missing_device_fingerprint"
    FINGERPRINT_EXHAUSTED = "fingerprint_exhausted"
    SUBNET_LIMIT = "subnet_limit"
    PROXY_OR_VPN = "proxy_or_vpn"
    STORE_UNAVAILABLE = "store_unavailable"


@dataclass(frozen=True, slots=True)
class SignupAbuseContext:
    """Client signals collected at the HTTP edge for signup abuse checks."""

    client_ip: str
    user_agent: str
    accept_language: str
    device_fingerprint: str


@dataclass(frozen=True, slots=True)
class TrialGrantDecision:
    """Outcome of evaluating whether to credit signup trial coins."""

    granted: bool
    denial_reason: TrialDenialReason | None = None
    fingerprint_hash: str | None = None
    ip_subnet: str | None = None


def compute_device_fingerprint_hash(
    *,
    device_fingerprint: str,
    user_agent: str,
    accept_language: str,
) -> str:
    """SHA-256 of ``X-Device-Fingerprint + User-Agent + Accept-Language``."""

    material = (
        f"{device_fingerprint.strip()}"
        f"{user_agent.strip()}"
        f"{accept_language.strip()}"
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def ipv4_subnet_24(ip: str) -> str | None:
    """Return the IPv4 ``/24`` network string (e.g. ``192.168.1.0/24``).

    IPv6 addresses are mapped to their ``/64`` network for an equivalent
    coarse bucket. Invalid / unknown IPs return ``None``.
    """

    value = (ip or "").strip()
    if not value or value.lower() in {"unknown", "localhost"}:
        return None
    try:
        parsed = ip_address(value)
    except ValueError:
        return None
    if isinstance(parsed, IPv4Address):
        network = ip_network(f"{parsed}/24", strict=False)
        return str(network)
    if isinstance(parsed, IPv6Address):
        network = ip_network(f"{parsed}/64", strict=False)
        return str(network)
    return None


def decide_trial_after_checks(
    *,
    fingerprint_hash: str | None,
    fingerprint_exhausted: bool,
    subnet: str | None,
    subnet_registration_count: int,
    subnet_max_accounts: int,
    is_proxy_or_vpn: bool,
    device_fingerprint_present: bool,
) -> TrialGrantDecision:
    """Apply ordered anti-abuse gates for the signup trial bonus.

    Order: missing fingerprint → exhausted fingerprint → subnet → proxy/VPN.
    """

    if not device_fingerprint_present or not fingerprint_hash:
        return TrialGrantDecision(
            granted=False,
            denial_reason=TrialDenialReason.MISSING_DEVICE_FINGERPRINT,
            fingerprint_hash=fingerprint_hash,
            ip_subnet=subnet,
        )
    if fingerprint_exhausted:
        return TrialGrantDecision(
            granted=False,
            denial_reason=TrialDenialReason.FINGERPRINT_EXHAUSTED,
            fingerprint_hash=fingerprint_hash,
            ip_subnet=subnet,
        )
    if subnet is not None and subnet_registration_count > subnet_max_accounts:
        return TrialGrantDecision(
            granted=False,
            denial_reason=TrialDenialReason.SUBNET_LIMIT,
            fingerprint_hash=fingerprint_hash,
            ip_subnet=subnet,
        )
    if is_proxy_or_vpn:
        return TrialGrantDecision(
            granted=False,
            denial_reason=TrialDenialReason.PROXY_OR_VPN,
            fingerprint_hash=fingerprint_hash,
            ip_subnet=subnet,
        )
    return TrialGrantDecision(
        granted=True,
        denial_reason=None,
        fingerprint_hash=fingerprint_hash,
        ip_subnet=subnet,
    )
