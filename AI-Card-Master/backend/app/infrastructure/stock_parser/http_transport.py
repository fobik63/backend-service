"""Shared httpx transport with mobile headers + rotating proxy pool."""

from __future__ import annotations

import logging
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


class MobileJsonTransport:
    """Thin async HTTP client dedicated to marketplace mobile JSON endpoints."""

    def __init__(
        self,
        *,
        marketplace: ParserMarketplace,
        proxy_pool: ProxyPool | None = None,
        timeout_seconds: float = 20.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._marketplace = marketplace
        self._proxy_pool = proxy_pool or ProxyPool(())
        self._timeout = httpx.Timeout(timeout_seconds)
        self._external_client = client
        self._owned_client: httpx.AsyncClient | None = None

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

    async def get_json(
        self,
        url: str,
        *,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """GET JSON with mobile UA; rotate proxy per request when configured."""

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
