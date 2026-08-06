"""Cloudflare API helpers for origin protection and automated IP bans."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.core.config import Settings, get_settings

logger = logging.getLogger(__name__)


class CloudflareError(RuntimeError):
    """Cloudflare API call failed."""


class CloudflareClient:
    """Minimal Cloudflare Firewall Access Rules client.

    Used to push temporary IP bans discovered by SuspiciousActivityMiddleware.
    DNS orange-cloud + origin firewall (allow Cloudflare IPs only) must still be
    configured in the Cloudflare dashboard / host firewall — this client only
    automates WAF/firewall rule updates.
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._api_token = (
            self._settings.cloudflare_api_token.get_secret_value().strip()
            if self._settings.cloudflare_api_token is not None
            else ""
        )
        self._zone_id = self._settings.cloudflare_zone_id.strip()
        self._account_id = self._settings.cloudflare_account_id.strip()
        self._base_url = self._settings.cloudflare_api_base_url.rstrip("/")
        self._timeout = httpx.Timeout(self._settings.cloudflare_timeout_seconds)

    @property
    def is_configured(self) -> bool:
        return bool(self._api_token and (self._zone_id or self._account_id))

    async def ban_ip(
        self,
        ip: str,
        *,
        reason: str,
        mode: str = "block",
    ) -> bool:
        """Create a firewall access rule blocking ``ip``. Returns False if skipped."""

        if not self._settings.cloudflare_enabled or not self.is_configured:
            return False
        if not self._settings.cloudflare_auto_ban_enabled:
            return False

        target_id = self._zone_id or self._account_id
        scope = "zones" if self._zone_id else "accounts"
        url = f"{self._base_url}/client/v4/{scope}/{target_id}/firewall/access_rules/rules"
        headers = {
            "Authorization": f"Bearer {self._api_token}",
            "Content-Type": "application/json",
        }
        payload: dict[str, Any] = {
            "mode": mode,
            "configuration": {"target": "ip", "value": ip},
            "notes": f"AI-Card-Master auto-ban: {reason[:200]}",
        }
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(url, headers=headers, json=payload)
                if response.status_code in {200, 201}:
                    body = response.json()
                    if body.get("success") is True:
                        logger.info("Cloudflare banned IP %s (%s)", ip, reason)
                        return True
                logger.warning(
                    "Cloudflare ban_ip failed for %s: status=%s body=%s",
                    ip,
                    response.status_code,
                    response.text[:300],
                )
                return False
        except Exception:
            logger.warning("Cloudflare ban_ip request error for %s", ip, exc_info=True)
            return False

    async def verify_zone_access(self) -> bool:
        """Lightweight connectivity check used by admin readiness probes."""

        if not self.is_configured:
            return False
        if not self._zone_id:
            return False
        url = f"{self._base_url}/client/v4/zones/{self._zone_id}"
        headers = {"Authorization": f"Bearer {self._api_token}"}
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.get(url, headers=headers)
                if response.status_code != 200:
                    return False
                body = response.json()
                return bool(body.get("success"))
        except Exception:
            logger.warning("Cloudflare zone verify failed", exc_info=True)
            return False


_client: CloudflareClient | None = None


def get_cloudflare_client() -> CloudflareClient:
    global _client
    if _client is None:
        _client = CloudflareClient()
    return _client
