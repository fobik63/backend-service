"""Outbound HTTP client for the n8n generate-pipeline webhook."""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlparse

import httpx

from app.application.generate_pipeline_errors import (
    GeneratePipelineNotConfiguredError,
    GeneratePipelineTimeoutError,
    GeneratePipelineUpstreamError,
    GeneratePipelineValidationError,
)
from app.core.config import Settings, get_settings
from app.infrastructure.http_resilience import (
    TRANSIENT_HTTP_CODES,
    call_with_transport_retry,
)

logger = logging.getLogger(__name__)


class N8nPipelineClient:
    """POST product JSON to n8n and return the raw JSON object response."""

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._http_client = http_client

    def _require_webhook_url(self) -> str:
        raw = (self._settings.n8n_webhook_url or "").strip()
        if not raw:
            raise GeneratePipelineNotConfiguredError(
                "N8N_WEBHOOK_URL is not configured.",
            )
        parsed = urlparse(raw)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise GeneratePipelineNotConfiguredError(
                "N8N_WEBHOOK_URL must be an absolute http(s) URL.",
            )
        return raw

    def _timeout(self) -> httpx.Timeout:
        return httpx.Timeout(
            self._settings.n8n_timeout_seconds,
            connect=self._settings.n8n_connect_timeout_seconds,
        )

    def _headers(self) -> dict[str, str]:
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        secret = self._settings.n8n_webhook_secret.get_secret_value().strip()
        if secret:
            headers["X-N8N-Webhook-Secret"] = secret
        return headers

    async def invoke(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Call n8n and parse a JSON object body."""

        webhook_url = self._require_webhook_url()
        headers = self._headers()
        timeout = self._timeout()
        max_retries = self._settings.n8n_max_retries

        async def _once() -> httpx.Response:
            if self._http_client is not None:
                return await self._http_client.post(
                    webhook_url,
                    json=payload,
                    headers=headers,
                    timeout=timeout,
                )
            async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
                return await client.post(
                    webhook_url,
                    json=payload,
                    headers=headers,
                )

        try:
            response = await call_with_transport_retry(
                _once,
                max_retries=max_retries,
                base_delay_seconds=0.4,
                operation_name="n8n.generate_pipeline",
                is_transient_result=lambda resp: resp.status_code in TRANSIENT_HTTP_CODES,
            )
        except httpx.TimeoutException as exc:
            logger.warning(
                "n8n generate-pipeline timed out url=%s",
                webhook_url,
            )
            raise GeneratePipelineTimeoutError(
                "n8n webhook timed out while processing the pipeline.",
            ) from exc
        except httpx.HTTPError as exc:
            logger.exception(
                "n8n generate-pipeline transport failure url=%s",
                webhook_url,
            )
            raise GeneratePipelineUpstreamError(
                "Failed to reach the n8n webhook.",
            ) from exc

        if response.status_code >= 400:
            body_preview = (response.text or "")[:500]
            logger.warning(
                "n8n generate-pipeline HTTP %s url=%s body=%s",
                response.status_code,
                webhook_url,
                body_preview,
            )
            raise GeneratePipelineUpstreamError(
                f"n8n webhook returned HTTP {response.status_code}.",
            )

        try:
            data = response.json()
        except ValueError as exc:
            logger.warning(
                "n8n generate-pipeline returned non-JSON url=%s content_type=%s",
                webhook_url,
                response.headers.get("content-type"),
            )
            raise GeneratePipelineValidationError(
                "n8n webhook returned a non-JSON response.",
            ) from exc

        if not isinstance(data, dict):
            raise GeneratePipelineValidationError(
                "n8n webhook must return a JSON object.",
            )
        return data
