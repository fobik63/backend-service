"""Midjourney / Claude balance & reachability probes (plan §62)."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

import httpx

from app.core.config import Settings, get_settings
from app.domain.security_status import ApiBalanceHealth, ApiBalanceStatus

logger = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(UTC)


def _classify_balance(
    balance: float | None,
    *,
    low_threshold: float,
) -> ApiBalanceHealth:
    if balance is None:
        return "unknown"
    if balance <= 0:
        return "exhausted"
    if balance <= low_threshold:
        return "low"
    return "ok"


def _extract_numeric_balance(payload: Any) -> tuple[float | None, str | None]:
    """Best-effort parse of common provider balance JSON shapes."""

    if not isinstance(payload, dict):
        return None, None

    candidates: list[tuple[str, Any]] = []
    for key in (
        "balance",
        "credits",
        "remaining",
        "remaining_credits",
        "credit",
        "usd",
        "amount",
    ):
        if key in payload:
            candidates.append((key, payload[key]))

    nested = payload.get("data")
    if isinstance(nested, dict):
        for key in ("balance", "credits", "remaining", "usd"):
            if key in nested:
                candidates.append((key, nested[key]))
        account = nested.get("account")
        if isinstance(account, dict):
            for key in ("balance", "credits", "remaining"):
                if key in account:
                    candidates.append((key, account[key]))

    for key, value in candidates:
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        unit = "credits" if "credit" in key else "usd" if key == "usd" else key
        return number, unit
    return None, None


class HttpApiBalanceProbes:
    """Lightweight HTTP probes for Midjourney gateway and Anthropic Claude."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()

    async def probe_midjourney(self) -> ApiBalanceStatus:
        settings = self._settings
        providers = settings.midjourney_providers
        api_key = (
            settings.midjourney_api_key.get_secret_value().strip()
            if settings.midjourney_api_key is not None
            else ""
        )
        base_url = settings.midjourney_base_url.strip().rstrip("/")
        if providers:
            primary = providers[0]
            api_key = primary.api_key.get_secret_value().strip()
            base_url = primary.base_url.strip().rstrip("/")

        if not api_key or not base_url:
            return ApiBalanceStatus(
                provider="midjourney",
                status="misconfigured",
                message="MIDJOURNEY_API_KEY / BASE_URL (or providers) not configured.",
                checked_at=_now(),
            )

        balance_path = settings.midjourney_balance_path.strip()
        timeout = httpx.Timeout(settings.security_status_api_probe_timeout_seconds)
        headers = {"Authorization": f"Bearer {api_key}", "Accept": "application/json"}

        try:
            async with httpx.AsyncClient(
                base_url=base_url,
                timeout=timeout,
                headers=headers,
                follow_redirects=True,
            ) as client:
                if balance_path:
                    response = await client.get(
                        balance_path if balance_path.startswith("/") else f"/{balance_path}"
                    )
                    body: Any
                    try:
                        body = response.json()
                    except Exception:
                        body = {"text": response.text[:500]}
                    if response.status_code >= 500:
                        return ApiBalanceStatus(
                            provider="midjourney",
                            status="unreachable",
                            message=f"Upstream HTTP {response.status_code}",
                            checked_at=_now(),
                            raw={"status_code": response.status_code},
                        )
                    if response.status_code in {401, 403}:
                        return ApiBalanceStatus(
                            provider="midjourney",
                            status="exhausted",
                            message="API key rejected by Midjourney provider.",
                            checked_at=_now(),
                            raw={"status_code": response.status_code},
                        )
                    balance, unit = _extract_numeric_balance(body)
                    health = (
                        _classify_balance(
                            balance,
                            low_threshold=settings.midjourney_balance_low_threshold,
                        )
                        if balance is not None
                        else ("ok" if response.is_success else "unknown")
                    )
                    return ApiBalanceStatus(
                        provider="midjourney",
                        status=health,
                        balance=balance,
                        currency="USD" if unit == "usd" else None,
                        unit=unit,
                        message=None if response.is_success else f"HTTP {response.status_code}",
                        checked_at=_now(),
                        raw={"status_code": response.status_code},
                    )

                # No balance path: reachability ping against provider root.
                response = await client.get("/")
                if response.status_code in {401, 403}:
                    # Auth required on root still proves the key path is live enough.
                    return ApiBalanceStatus(
                        provider="midjourney",
                        status="ok",
                        message="Provider reachable (auth challenged on root).",
                        checked_at=_now(),
                        raw={"status_code": response.status_code},
                    )
                if response.status_code >= 500:
                    return ApiBalanceStatus(
                        provider="midjourney",
                        status="unreachable",
                        message=f"Upstream HTTP {response.status_code}",
                        checked_at=_now(),
                        raw={"status_code": response.status_code},
                    )
                return ApiBalanceStatus(
                    provider="midjourney",
                    status="ok",
                    message="Provider reachable; balance path not configured.",
                    checked_at=_now(),
                    raw={"status_code": response.status_code},
                )
        except httpx.TimeoutException:
            return ApiBalanceStatus(
                provider="midjourney",
                status="unreachable",
                message="Midjourney probe timed out.",
                checked_at=_now(),
            )
        except Exception as exc:
            logger.warning("Midjourney balance probe failed: %s", exc)
            return ApiBalanceStatus(
                provider="midjourney",
                status="unreachable",
                message=str(exc)[:240],
                checked_at=_now(),
            )

    async def probe_claude(self) -> ApiBalanceStatus:
        settings = self._settings
        api_key = (
            settings.claude_47_api_key.get_secret_value().strip()
            if settings.claude_47_api_key is not None
            else ""
        )
        if not api_key:
            return ApiBalanceStatus(
                provider="claude",
                status="misconfigured",
                message="CLAUDE_47_API_KEY is not configured.",
                checked_at=_now(),
            )

        base = settings.claude_47_base_url.strip().rstrip("/") or "https://api.anthropic.com"
        timeout = httpx.Timeout(settings.security_status_api_probe_timeout_seconds)
        headers = {
            "x-api-key": api_key,
            "anthropic-version": settings.claude_47_api_version,
            "Accept": "application/json",
        }

        try:
            async with httpx.AsyncClient(
                base_url=base,
                timeout=timeout,
                headers=headers,
                follow_redirects=True,
            ) as client:
                # Anthropic has no universal public "balance" endpoint for all keys;
                # /v1/models validates the key and account health.
                response = await client.get("/v1/models")
                if response.status_code in {401, 403}:
                    return ApiBalanceStatus(
                        provider="claude",
                        status="exhausted",
                        message="Claude API key rejected or billing locked.",
                        checked_at=_now(),
                        raw={"status_code": response.status_code},
                    )
                if response.status_code == 429:
                    return ApiBalanceStatus(
                        provider="claude",
                        status="low",
                        message="Claude rate-limited (quota pressure).",
                        checked_at=_now(),
                        raw={"status_code": response.status_code},
                    )
                if response.status_code >= 500:
                    return ApiBalanceStatus(
                        provider="claude",
                        status="unreachable",
                        message=f"Anthropic HTTP {response.status_code}",
                        checked_at=_now(),
                        raw={"status_code": response.status_code},
                    )
                if response.is_success:
                    return ApiBalanceStatus(
                        provider="claude",
                        status="ok",
                        message="Claude API key accepted.",
                        checked_at=_now(),
                        raw={"status_code": response.status_code},
                    )
                return ApiBalanceStatus(
                    provider="claude",
                    status="unknown",
                    message=f"Unexpected HTTP {response.status_code}",
                    checked_at=_now(),
                    raw={"status_code": response.status_code},
                )
        except httpx.TimeoutException:
            return ApiBalanceStatus(
                provider="claude",
                status="unreachable",
                message="Claude probe timed out.",
                checked_at=_now(),
            )
        except Exception as exc:
            logger.warning("Claude balance probe failed: %s", exc)
            return ApiBalanceStatus(
                provider="claude",
                status="unreachable",
                message=str(exc)[:240],
                checked_at=_now(),
            )
