"""Resolve the real client IP behind Cloudflare / reverse proxies."""

from __future__ import annotations

from ipaddress import ip_address, ip_network
from typing import Iterable

from fastapi import Request

# Cloudflare published IPv4/IPv6 ranges (static fallback; refresh via CF API optionally).
# Source: https://www.cloudflare.com/ips/
_CLOUDFLARE_IPV4_CIDRS: tuple[str, ...] = (
    "173.245.48.0/20",
    "103.21.244.0/22",
    "103.22.200.0/22",
    "103.31.4.0/22",
    "141.101.64.0/18",
    "108.162.192.0/18",
    "190.93.240.0/20",
    "188.114.96.0/20",
    "197.234.240.0/22",
    "198.41.128.0/17",
    "162.158.0.0/15",
    "104.16.0.0/13",
    "104.24.0.0/14",
    "172.64.0.0/13",
    "131.0.72.0/22",
)
_CLOUDFLARE_IPV6_CIDRS: tuple[str, ...] = (
    "2400:cb00::/32",
    "2606:4700::/32",
    "2803:f800::/32",
    "2405:b500::/32",
    "2405:8100::/32",
    "2a06:98c0::/29",
    "2c0f:f248::/32",
)

_CF_NETWORKS = tuple(
    ip_network(cidr) for cidr in (*_CLOUDFLARE_IPV4_CIDRS, *_CLOUDFLARE_IPV6_CIDRS)
)


def is_cloudflare_edge_ip(ip: str) -> bool:
    """Return True when ``ip`` belongs to a known Cloudflare edge range."""

    try:
        parsed = ip_address(ip.strip())
    except ValueError:
        return False
    return any(parsed in network for network in _CF_NETWORKS)


def parse_trusted_proxy_cidrs(raw: str) -> tuple[object, ...]:
    """Parse comma-separated CIDRs / single IPs into network objects."""

    networks: list[object] = []
    for part in raw.split(","):
        value = part.strip()
        if not value:
            continue
        try:
            if "/" in value:
                networks.append(ip_network(value, strict=False))
            else:
                networks.append(ip_network(f"{value}/32" if ":" not in value else f"{value}/128", strict=False))
        except ValueError:
            continue
    return tuple(networks)


def _peer_is_trusted(peer: str | None, trusted_networks: Iterable[object]) -> bool:
    if not peer:
        return False
    try:
        parsed = ip_address(peer.strip())
    except ValueError:
        return False
    for network in trusted_networks:
        if parsed in network:  # type: ignore[operator]
            return True
    return False


def resolve_client_ip(
    request: Request,
    *,
    trust_cloudflare: bool = True,
    trusted_proxy_cidrs: str = "",
) -> str:
    """Return the best-effort client IP for rate limiting and abuse detection.

    When the immediate peer is Cloudflare (or an explicitly trusted proxy),
    prefer ``CF-Connecting-IP``, then the left-most ``X-Forwarded-For`` hop.
    Otherwise fall back to ``request.client.host`` and ignore spoofable headers.
    """

    peer = request.client.host if request.client is not None else None
    trusted = list(parse_trusted_proxy_cidrs(trusted_proxy_cidrs))
    if trust_cloudflare:
        trusted.extend(_CF_NETWORKS)

    if peer and _peer_is_trusted(peer, trusted):
        cf_ip = (request.headers.get("CF-Connecting-IP") or "").strip()
        if cf_ip:
            try:
                ip_address(cf_ip)
                return cf_ip
            except ValueError:
                pass
        forwarded = (request.headers.get("X-Forwarded-For") or "").split(",")[0].strip()
        if forwarded:
            try:
                ip_address(forwarded)
                return forwarded
            except ValueError:
                pass

    return peer or "unknown"
