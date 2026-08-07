"""Lightweight async VPN / Proxy / Tor detection for signup trial gates.

Detection layers (fail-open on transport errors so legitimate users are not
blocked by DNS/API outages; positive hits deny the trial only):

1. Tor DNSBL (``dnsel.torproject.org``)
2. Reverse DNS (PTR) keyword heuristics (vpn, proxy, tor, exit, …)
3. Optional open IP reputation JSON (``ip-api.com`` proxy/hosting flags)
"""

from __future__ import annotations

import asyncio
import logging
import socket
from ipaddress import IPv4Address, IPv6Address, ip_address

import httpx

logger = logging.getLogger(__name__)

_PTR_SUSPICIOUS_TOKENS: frozenset[str] = frozenset(
    {
        "vpn",
        "proxy",
        "tor-exit",
        "tor.exit",
        "torservers",
        "anonymizer",
        "nordvpn",
        "expressvpn",
        "surfshark",
        "cyberghost",
        "privateinternetaccess",
        "protonvpn",
        "mullvad",
        "hide.me",
        "hidemyass",
        "tunnelbear",
        "windscribe",
        "ipvanish",
        "ovpn",
        "openvpn",
        "socks5",
        "leaseweb",
        "choopa",
        "digitalocean",
        "linode",
        "vultr",
        "hetzner",
        "contabo",
        "ovh.net",
        "amazonaws",
        "googleusercontent",
        "softlayer",
        "psychz",
        "quadranet",
        "colocrossing",
    }
)


def _reverse_octets_ipv4(ip: IPv4Address) -> str:
    return ".".join(reversed(str(ip).split(".")))


async def _resolve_ptr(ip: str) -> str | None:
    """Best-effort PTR lookup; returns the first hostname or ``None``."""

    loop = asyncio.get_running_loop()

    def _lookup() -> str | None:
        try:
            host, _aliases, _ips = socket.gethostbyaddr(ip)
            return (host or "").strip().lower() or None
        except (socket.herror, socket.gaierror, OSError):
            return None

    return await loop.run_in_executor(None, _lookup)


def _ptr_looks_suspicious(hostname: str | None) -> bool:
    if not hostname:
        return False
    lowered = hostname.lower()
    return any(token in lowered for token in _PTR_SUSPICIOUS_TOKENS)


async def _is_tor_exit_dnsbl(ip: str) -> bool:
    """Query Tor Project DNSBL: ``{reversed}.dnsel.torproject.org``."""

    try:
        parsed = ip_address(ip)
    except ValueError:
        return False
    if not isinstance(parsed, IPv4Address):
        # Tor DNSBL is IPv4-oriented; skip IPv6 here.
        return False

    query = f"{_reverse_octets_ipv4(parsed)}.dnsel.torproject.org"
    loop = asyncio.get_running_loop()

    def _lookup() -> bool:
        try:
            socket.getaddrinfo(query, None, family=socket.AF_INET)
            return True
        except socket.gaierror:
            return False
        except OSError:
            return False

    return await loop.run_in_executor(None, _lookup)


class AsyncProxyDetector:
    """Compose Tor DNSBL + PTR heuristics + optional open reputation API."""

    def __init__(
        self,
        *,
        enabled: bool = True,
        use_ip_api: bool = True,
        timeout_seconds: float = 2.5,
    ) -> None:
        self._enabled = enabled
        self._use_ip_api = use_ip_api
        self._timeout = timeout_seconds

    async def is_proxy_or_vpn(self, *, ip: str) -> bool:
        if not self._enabled:
            return False
        value = (ip or "").strip()
        if not value or value.lower() in {"unknown", "localhost", "127.0.0.1", "::1"}:
            return False
        try:
            parsed = ip_address(value)
        except ValueError:
            return False
        if parsed.is_private or parsed.is_loopback or parsed.is_link_local:
            return False

        try:
            if await _is_tor_exit_dnsbl(value):
                logger.info("Signup trial denied: Tor exit node %s", value)
                return True
        except Exception:
            logger.debug("Tor DNSBL check failed for %s", value, exc_info=True)

        try:
            ptr = await _resolve_ptr(value)
            if _ptr_looks_suspicious(ptr):
                logger.info(
                    "Signup trial denied: suspicious PTR %s → %s",
                    value,
                    ptr,
                )
                return True
        except Exception:
            logger.debug("PTR lookup failed for %s", value, exc_info=True)

        if self._use_ip_api and isinstance(parsed, (IPv4Address, IPv6Address)):
            try:
                if await self._ip_api_proxy_or_hosting(value):
                    logger.info(
                        "Signup trial denied: ip-api proxy/hosting flag for %s",
                        value,
                    )
                    return True
            except Exception:
                logger.debug("ip-api check failed for %s", value, exc_info=True)

        return False

    async def _ip_api_proxy_or_hosting(self, ip: str) -> bool:
        """Query the free non-commercial ip-api.com endpoint (no key)."""

        url = (
            f"http://ip-api.com/json/{ip}"
            f"?fields=status,proxy,hosting,message"
        )
        timeout = httpx.Timeout(self._timeout)
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(url)
            response.raise_for_status()
            payload = response.json()
        if not isinstance(payload, dict):
            return False
        if payload.get("status") != "success":
            return False
        return bool(payload.get("proxy")) or bool(payload.get("hosting"))
