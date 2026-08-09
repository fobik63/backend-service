"""Shared httpx transport with mobile headers + rotating proxy pool.

Applies a jittered inter-request delay so sequential WB/Ozon calls from a
single egress IP are less likely to trip marketplace rate limits.
"""

from __future__ import annotations

import asyncio
import logging
import random
from typing import Any

import httpx

from app.domain.stock_parser import ParserMarketplace, classify_http_status
from app.infrastructure.stock_parser.exceptions import (
    ParserHttpError,
    ParserTransportError,
)
from app.infrastructure.stock_parser.mobile_headers import mobile_headers
from app.infrastructure.stock_parser.proxy_pool import ProxyPool

logger = logging.getLogger(__name__)

# Conservative defaults when callers omit delay settings (local / CI).
DEFAULT_REQUEST_DELAY_MIN_SECONDS = 0.4
DEFAULT_REQUEST_DELAY_MAX_SECONDS = 1.2


class MobileJsonTransport:
    """Thin async HTTP client dedicated to marketplace mobile JSON endpoints."""

    def __init__(
        self,
        *,
        marketplace: ParserMarketplace,
        proxy_pool: ProxyPool | None = None,
        timeout_seconds: float = 20.0,
        client: httpx.AsyncClient | None = None,
        request_delay_min_seconds: float = DEFAULT_REQUEST_DELAY_MIN_SECONDS,
        request_delay_max_seconds: float = DEFAULT_REQUEST_DELAY_MAX_SECONDS,
    ) -> None:
        self._marketplace = marketplace
        self._proxy_pool = proxy_pool or ProxyPool(())
        self._timeout = httpx.Timeout(timeout_seconds)
        self._external_client = client
        self._owned_client: httpx.AsyncClient | None = None
        min_delay = max(0.0, float(request_delay_min_seconds))
        max_delay = max(min_delay, float(request_delay_max_seconds))
        self._delay_min = min_delay
        self._delay_max = max_delay
        self._had_prior_request = False

    async def _client(self) -> httpx.AsyncClient:
        if self._external_client is not None:
            return self._external_client
        if self._owned_client is None:
            self._owned_client = httpx.AsyncClient(
                timeout=self._timeout,
                follow_redirects=True,
                http2=True,
            )
        return self._owned_client

    async def _throttle(self) -> None:
        """Sleep a jittered gap between marketplace requests."""

        if self._delay_max <= 0:
            return
        if not self._had_prior_request:
            # Opening jitter so the first hit is not perfectly timed.
            opening = random.uniform(0.0, min(0.25, self._delay_min or 0.25))
            if opening > 0:
                await asyncio.sleep(opening)
            self._had_prior_request = True
            return

        delay = random.uniform(self._delay_min, self._delay_max)
        if delay > 0:
            await asyncio.sleep(delay)
        self._had_prior_request = True

    async def get_json(
        self,
        url: str,
        *,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """GET JSON with rotating mobile UA + optional proxy + request delay."""

        await self._throttle()
        # Fresh headers (incl. User-Agent) on every call.
        headers = mobile_headers(marketplace=self._marketplace.value)
        proxy = self._proxy_pool.next()
        proxy_url = proxy.as_httpx_proxy() if proxy is not None else None

        try:
            if proxy_url is not None:
                # Per-request proxy via a short-lived client (httpx 0.28 mounts).
                async with httpx.AsyncClient(
                    timeout=self._timeout,
                    follow_redirects=True,
                    proxy=proxy_url,
                    http2=True,
                ) as proxied:
                    response = await proxied.get(url, params=params, headers=headers)
            else:
                client = await self._client()
                response = await client.get(url, params=params, headers=headers)
        except httpx.TimeoutException as exc:
            raise ParserTransportError(
                f"Timeout calling {url}: {exc}",
                marketplace=self._marketplace,
            ) from exc
        except httpx.HTTPError as exc:
            raise ParserTransportError(
                f"Transport error calling {url}: {exc}",
                marketplace=self._marketplace,
            ) from exc

        if response.status_code >= 400:
            kind = classify_http_status(response.status_code)
            body_preview = response.text[:300]
            raise ParserHttpError(
                f"HTTP {response.status_code} from {url}: {body_preview}",
                marketplace=self._marketplace,
                status_code=response.status_code,
                kind=kind,
            )

        try:
            payload = response.json()
        except ValueError as exc:
            raise ParserTransportError(
                f"Non-JSON body from {url}",
                marketplace=self._marketplace,
            ) from exc

        if not isinstance(payload, dict):
            raise ParserTransportError(
                f"JSON root must be an object from {url}",
                marketplace=self._marketplace,
            )
        return payload

    async def aclose(self) -> None:
        if self._owned_client is not None:
            await self._owned_client.aclose()
            self._owned_client = None
