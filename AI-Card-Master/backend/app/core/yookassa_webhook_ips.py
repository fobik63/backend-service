"""Official YooKassa notification IP ranges (webhook source allowlist).

Source: https://yookassa.ru/developers/using-api/webhooks#ip
Refresh this module when YooKassa publishes an updated list.
"""

from __future__ import annotations

from ipaddress import ip_address, ip_network
from typing import Final

from fastapi import Request

from app.core.client_ip import resolve_client_ip
from app.core.config import get_settings

# Official IPv4/IPv6 ranges published by YooKassa for incoming notifications.
YOOKASSA_NOTIFICATION_CIDRS: Final[tuple[str, ...]] = (
    "185.71.76.0/27",
    "185.71.77.0/27",
    "77.75.153.0/25",
    "77.75.156.11/32",
    "77.75.156.35/32",
    "77.75.154.128/25",
    "2a02:5180::/32",
)

_YOOKASSA_NETWORKS = tuple(
    ip_network(cidr, strict=False) for cidr in YOOKASSA_NOTIFICATION_CIDRS
)

YOOKASSA_WEBHOOK_PATH: Final[str] = "/api/v1/billing/webhook/yookassa"
YOOKASSA_TARIFF_WEBHOOK_PATH: Final[str] = "/api/v1/payments/webhook"
YOOKASSA_WEBHOOK_PATHS: Final[frozenset[str]] = frozenset(
    {YOOKASSA_WEBHOOK_PATH, YOOKASSA_TARIFF_WEBHOOK_PATH}
)


def is_yookassa_notification_ip(ip: str) -> bool:
    """Return True when ``ip`` belongs to a published YooKassa notification range."""

    try:
        parsed = ip_address(ip.strip())
    except ValueError:
        return False
    return any(parsed in network for network in _YOOKASSA_NETWORKS)


def resolve_webhook_source_ip(request: Request) -> str:
    """Best-effort source IP: CF-Connecting-IP behind a trusted proxy, else peer."""

    settings = get_settings()
    return resolve_client_ip(
        request,
        trust_cloudflare=settings.cloudflare_trust_headers,
        trusted_proxy_cidrs=settings.trusted_proxy_cidrs,
    )


def is_yookassa_webhook_path(path: str) -> bool:
    """Return True when ``path`` is a YooKassa notification URL we accept."""

    return path in YOOKASSA_WEBHOOK_PATHS


def is_allowed_yookassa_webhook_request(request: Request) -> bool:
    """Whether this request is allowed to hit a YooKassa webhook endpoint."""

    settings = get_settings()
    enforce = bool(settings.yookassa_webhook_ip_enforcement)
    if settings.app_env == "production":
        enforce = True
    if not enforce:
        return True
    source_ip = resolve_webhook_source_ip(request)
    return is_yookassa_notification_ip(source_ip)
