"""AI image generation engine: Stable Diffusion + Midjourney (tariff-aware).

This module provides async services that send product images to upstream
generation APIs and return generated image bytes.

Existing Stable Diffusion image-to-image flow is preserved.
Midjourney integration is layered on top and selected by subscription tariff:
- Free  -> Stable Diffusion (fast / cost-efficient baseline)
- Pro   -> Midjourney (higher photorealism, premium parameters)

Key features:
- async requests via httpx with connection pooling;
- retry strategy for transient upstream failures;
- automatic "golden prompt" enrichment;
- hidden negative prompt for artifact suppression;
- tariff-based engine routing;
- strict input validation and explicit error contracts.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import hashlib
import hmac
import ipaddress
import json
import logging
import os
import random
import socket
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Final, Literal
from urllib.parse import urlparse

import httpx
from pydantic import HttpUrl, TypeAdapter

from app.core.config import get_settings
from app.domain.generation import ProviderSubmission, ProviderWebhookEvent
from app.infrastructure.redis import (
    is_provider_circuit_open,
    record_provider_failure,
    record_provider_success,
)
from app.models.enums import SubscriptionStatus


logger = logging.getLogger(__name__)


class AIEngineProvider(StrEnum):
    """Supported image generation providers."""

    STABLE_DIFFUSION = "stable_diffusion"
    MIDJOURNEY = "midjourney"


# Automatically appended to every user request.
GOLDEN_PROMPT_SUFFIX: Final[str] = "lighting: golden hour, high-end retouch, 8k"


# Hidden negative prompt: it is always applied and is not exposed in the function signature.
HIDDEN_NEGATIVE_PROMPT: Final[str] = "extra objects, blurry, distorted"


# Transient statuses that should be retried with backoff.
TRANSIENT_HTTP_CODES: Final[set[int]] = {408, 425, 429, 500, 502, 503, 504}


class AIEngineError(Exception):
    """Base exception for AI engine failures."""


class AIEngineConfigurationError(AIEngineError):
    """Raised when service configuration is invalid."""


class AIEngineValidationError(AIEngineError):
    """Raised when caller input is invalid before hitting upstream API."""


class AIEngineUpstreamError(AIEngineError):
    """Raised when Stable Diffusion API returns an error or invalid payload."""


class AIEngineRateLimitError(AIEngineUpstreamError):
    """Provider exhausted its current quota or rate window."""


class AIEngineModerationError(AIEngineUpstreamError):
    """Provider rejected input under its content policy."""


@dataclass(frozen=True, slots=True)
class StableDiffusionConfig:
    """Runtime config for Stable Diffusion HTTP integration.

    The defaults are production-friendly and can be overridden by env vars.
    """

    api_key: str
    base_url: str = "https://api.stability.ai"
    engine_id: str = "stable-diffusion-xl-1024-v1-0"
    timeout_seconds: float = 60.0
    connect_timeout_seconds: float = 8.0
    max_connections: int = 300
    max_keepalive_connections: int = 120
    keepalive_expiry_seconds: float = 30.0
    max_parallel_requests: int = 200
    max_retries: int = 3
    base_retry_delay_seconds: float = 0.35
    image_strength: float = 0.35
    cfg_scale: int = 8
    steps: int = 30

    @classmethod
    def from_env(cls) -> "StableDiffusionConfig":
        """Build config from environment variables.

        Required:
        - `STABLE_DIFFUSION_API_KEY`

        Optional:
        - `STABLE_DIFFUSION_BASE_URL`
        - `STABLE_DIFFUSION_ENGINE_ID`
        - `STABLE_DIFFUSION_TIMEOUT_SECONDS`
        - `STABLE_DIFFUSION_CONNECT_TIMEOUT_SECONDS`
        - `STABLE_DIFFUSION_MAX_CONNECTIONS`
        - `STABLE_DIFFUSION_MAX_KEEPALIVE_CONNECTIONS`
        - `STABLE_DIFFUSION_KEEPALIVE_EXPIRY_SECONDS`
        - `STABLE_DIFFUSION_MAX_PARALLEL_REQUESTS`
        - `STABLE_DIFFUSION_MAX_RETRIES`
        - `STABLE_DIFFUSION_BASE_RETRY_DELAY_SECONDS`
        - `STABLE_DIFFUSION_IMAGE_STRENGTH`
        - `STABLE_DIFFUSION_CFG_SCALE`
        - `STABLE_DIFFUSION_STEPS`
        """

        api_key = os.getenv("STABLE_DIFFUSION_API_KEY", "").strip()
        if not api_key:
            raise AIEngineConfigurationError(
                "Missing STABLE_DIFFUSION_API_KEY environment variable."
            )

        return cls(
            api_key=api_key,
            base_url=os.getenv("STABLE_DIFFUSION_BASE_URL", "https://api.stability.ai").strip(),
            engine_id=os.getenv(
                "STABLE_DIFFUSION_ENGINE_ID", "stable-diffusion-xl-1024-v1-0"
            ).strip(),
            timeout_seconds=_env_float("STABLE_DIFFUSION_TIMEOUT_SECONDS", 60.0),
            connect_timeout_seconds=_env_float(
                "STABLE_DIFFUSION_CONNECT_TIMEOUT_SECONDS", 8.0
            ),
            max_connections=_env_int("STABLE_DIFFUSION_MAX_CONNECTIONS", 300),
            max_keepalive_connections=_env_int(
                "STABLE_DIFFUSION_MAX_KEEPALIVE_CONNECTIONS", 120
            ),
            keepalive_expiry_seconds=_env_float(
                "STABLE_DIFFUSION_KEEPALIVE_EXPIRY_SECONDS", 30.0
            ),
            max_parallel_requests=_env_int("STABLE_DIFFUSION_MAX_PARALLEL_REQUESTS", 200),
            max_retries=_env_int("STABLE_DIFFUSION_MAX_RETRIES", 3),
            base_retry_delay_seconds=_env_float(
                "STABLE_DIFFUSION_BASE_RETRY_DELAY_SECONDS", 0.35
            ),
            image_strength=_env_float("STABLE_DIFFUSION_IMAGE_STRENGTH", 0.35),
            cfg_scale=_env_int("STABLE_DIFFUSION_CFG_SCALE", 8),
            steps=_env_int("STABLE_DIFFUSION_STEPS", 30),
        )

    @classmethod
    def from_settings(cls) -> "StableDiffusionConfig":
        """Build from the central Pydantic Settings object."""

        settings = get_settings()
        api_key = (
            settings.stable_diffusion_api_key.get_secret_value().strip()
            if settings.stable_diffusion_api_key is not None
            else ""
        )
        if not api_key:
            raise AIEngineConfigurationError(
                "Missing STABLE_DIFFUSION_API_KEY environment variable."
            )
        return cls(
            api_key=api_key,
            base_url=settings.stable_diffusion_base_url,
            engine_id=settings.stable_diffusion_engine_id,
            timeout_seconds=settings.stable_diffusion_timeout_seconds,
            connect_timeout_seconds=settings.stable_diffusion_connect_timeout_seconds,
            max_connections=settings.stable_diffusion_max_connections,
            max_keepalive_connections=(
                settings.stable_diffusion_max_keepalive_connections
            ),
            keepalive_expiry_seconds=(
                settings.stable_diffusion_keepalive_expiry_seconds
            ),
            max_parallel_requests=settings.stable_diffusion_max_parallel_requests,
            max_retries=settings.stable_diffusion_max_retries,
            base_retry_delay_seconds=(
                settings.stable_diffusion_base_retry_delay_seconds
            ),
            image_strength=settings.stable_diffusion_image_strength,
            cfg_scale=settings.stable_diffusion_cfg_scale,
            steps=settings.stable_diffusion_steps,
        )


class StableDiffusionService:
    """Async Stable Diffusion client optimized for high-throughput workloads."""

    def __init__(self, config: StableDiffusionConfig) -> None:
        if not config.base_url.strip():
            raise AIEngineConfigurationError("Stable Diffusion base URL must not be empty.")
        if not config.engine_id.strip():
            raise AIEngineConfigurationError("Stable Diffusion engine ID must not be empty.")
        if config.max_retries < 0:
            raise AIEngineConfigurationError("max_retries cannot be negative.")
        if config.max_parallel_requests <= 0:
            raise AIEngineConfigurationError("max_parallel_requests must be greater than zero.")

        self._config = config
        self._semaphore = asyncio.Semaphore(config.max_parallel_requests)

        # Reused AsyncClient is critical for high load:
        # - keeps TCP/TLS connections hot,
        # - minimizes handshake overhead,
        # - reduces per-request latency.
        self._client = httpx.AsyncClient(
            base_url=config.base_url.rstrip("/"),
            headers={
                "Authorization": f"Bearer {config.api_key}",
                "Accept": "application/json",
            },
            timeout=httpx.Timeout(
                timeout=config.timeout_seconds,
                connect=config.connect_timeout_seconds,
            ),
            limits=httpx.Limits(
                max_connections=config.max_connections,
                max_keepalive_connections=config.max_keepalive_connections,
                keepalive_expiry=config.keepalive_expiry_seconds,
            ),
            http2=True,
        )

    async def aclose(self) -> None:
        """Gracefully close underlying HTTP resources."""

        await self._client.aclose()

    async def generate_product_image(
        self,
        product_image: bytes,
        selected_style: str,
        user_text: str,
    ) -> bytes:
        """Generate stylized product image using Stable Diffusion image-to-image.

        Args:
            product_image: Source product image bytes.
            selected_style: Chosen style descriptor (for example: "minimal studio").
            user_text: User instruction text.

        Returns:
            Raw bytes of generated image.

        Raises:
            AIEngineValidationError: Invalid local input.
            AIEngineUpstreamError: Stable Diffusion request/response failure.
        """

        self._validate_input(product_image=product_image, selected_style=selected_style, user_text=user_text)

        merged_prompt = self._build_prompt(selected_style=selected_style, user_text=user_text)
        mime_type, extension = _detect_image_mime_type(product_image)

        endpoint = f"/v1/generation/{self._config.engine_id}/image-to-image"

        async with self._semaphore:
            response = await self._post_with_retry(
                endpoint=endpoint,
                product_image=product_image,
                mime_type=mime_type,
                extension=extension,
                prompt=merged_prompt,
            )

        return self._extract_generated_image(response)

    async def inpaint_product_edges(
        self,
        *,
        composited_image: bytes,
        edge_mask: bytes,
        prompt: str,
    ) -> bytes:
        """Inpaint only a narrow edge ring while preserving product pixels."""

        _detect_image_mime_type(composited_image)
        mask_mime, mask_extension = _detect_image_mime_type(edge_mask)
        if mask_mime != "image/png":
            raise AIEngineValidationError("Inpainting edge mask must be PNG.")
        endpoint = f"/v1/generation/{self._config.engine_id}/image-to-image/masking"
        data = {
            "text_prompts[0][text]": (
                f"{prompt.strip()}, seamless product edge integration, realistic contact light"
            ),
            "text_prompts[0][weight]": "1",
            "text_prompts[1][text]": HIDDEN_NEGATIVE_PROMPT,
            "text_prompts[1][weight]": "-1",
            "mask_source": "MASK_IMAGE_WHITE",
            "cfg_scale": str(self._config.cfg_scale),
            "steps": str(self._config.steps),
            "samples": "1",
        }
        files = {
            "init_image": ("composite.png", composited_image, "image/png"),
            "mask_image": (f"edge{mask_extension}", edge_mask, mask_mime),
        }
        last_error: Exception | None = None
        async with self._semaphore:
            for attempt in range(1, self._config.max_retries + 2):
                try:
                    response = await self._client.post(endpoint, data=data, files=files)
                    if (
                        response.status_code in TRANSIENT_HTTP_CODES
                        and attempt <= self._config.max_retries
                    ):
                        await asyncio.sleep(self._compute_retry_delay(attempt, response))
                        continue
                    response.raise_for_status()
                    return self._extract_generated_image(response)
                except (
                    httpx.TimeoutException,
                    httpx.NetworkError,
                    httpx.RemoteProtocolError,
                ) as exc:
                    last_error = exc
                    if attempt > self._config.max_retries:
                        break
                    await asyncio.sleep(self._compute_retry_delay(attempt, None))
                except httpx.HTTPStatusError as exc:
                    raise AIEngineUpstreamError(
                        f"Stable Diffusion inpaint returned {exc.response.status_code}: "
                        f"{_extract_error_message(exc.response)}"
                    ) from exc
        raise AIEngineUpstreamError(
            "Stable Diffusion inpainting is temporarily unavailable."
        ) from last_error

    def _validate_input(self, product_image: bytes, selected_style: str, user_text: str) -> None:
        """Validate caller payload before external request."""

        if not isinstance(product_image, (bytes, bytearray)):
            raise AIEngineValidationError("product_image must be bytes.")
        if not product_image:
            raise AIEngineValidationError("product_image cannot be empty.")
        if not selected_style or not selected_style.strip():
            raise AIEngineValidationError("selected_style cannot be empty.")
        if not user_text or not user_text.strip():
            raise AIEngineValidationError("user_text cannot be empty.")

    def _build_prompt(self, selected_style: str, user_text: str) -> str:
        """Merge user prompt, selected style, and mandatory golden prompt."""

        # Using comma-delimited prompt chunks keeps result deterministic and easy to inspect.
        prompt_chunks = [
            user_text.strip(),
            f"style: {selected_style.strip()}",
            GOLDEN_PROMPT_SUFFIX,
        ]
        return ", ".join(prompt_chunks)

    async def _post_with_retry(
        self,
        endpoint: str,
        product_image: bytes,
        mime_type: str,
        extension: str,
        prompt: str,
    ) -> httpx.Response:
        """Send request with exponential backoff retry for transient errors."""

        max_attempts = self._config.max_retries + 1
        last_error: Exception | None = None

        for attempt in range(1, max_attempts + 1):
            try:
                data = {
                    "text_prompts[0][text]": prompt,
                    "text_prompts[0][weight]": "1",
                    # Hidden negative prompt with negative weight to suppress artifacts.
                    "text_prompts[1][text]": HIDDEN_NEGATIVE_PROMPT,
                    "text_prompts[1][weight]": "-1",
                    "cfg_scale": str(self._config.cfg_scale),
                    "image_strength": str(self._config.image_strength),
                    "steps": str(self._config.steps),
                    "samples": "1",
                }
                files = {
                    "init_image": (
                        f"product{extension}",
                        product_image,
                        mime_type,
                    )
                }

                response = await self._client.post(endpoint, data=data, files=files)

                if response.status_code in TRANSIENT_HTTP_CODES and attempt < max_attempts:
                    await asyncio.sleep(self._compute_retry_delay(attempt, response))
                    continue

                response.raise_for_status()
                return response

            except (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError) as exc:
                last_error = exc
                if attempt >= max_attempts:
                    break
                await asyncio.sleep(self._compute_retry_delay(attempt, response=None))
            except httpx.HTTPStatusError as exc:
                status_code = exc.response.status_code
                if status_code in TRANSIENT_HTTP_CODES and attempt < max_attempts:
                    await asyncio.sleep(self._compute_retry_delay(attempt, exc.response))
                    continue
                error_message = _extract_error_message(exc.response)
                if status_code == 429:
                    raise AIEngineRateLimitError(
                        f"Stable Diffusion rate limit reached: {error_message}"
                    ) from exc
                if _looks_like_moderation_error(status_code, error_message):
                    raise AIEngineModerationError(
                        "Stable Diffusion rejected the image under its content policy."
                    ) from exc
                raise AIEngineUpstreamError(
                    f"Stable Diffusion API returned {status_code}: "
                    f"{error_message}"
                ) from exc

        raise AIEngineUpstreamError(
            "Stable Diffusion API is temporarily unavailable after retries."
        ) from last_error

    def _compute_retry_delay(self, attempt: int, response: httpx.Response | None) -> float:
        """Compute retry delay with Retry-After support and jitter.

        Jitter avoids synchronized retry storms under high load.
        """

        if response is not None:
            retry_after = response.headers.get("Retry-After")
            if retry_after:
                try:
                    parsed_retry_after = float(retry_after)
                    if parsed_retry_after > 0:
                        return min(parsed_retry_after, 10.0)
                except ValueError:
                    logger.debug("Non-numeric Retry-After header ignored: %s", retry_after)

        base = self._config.base_retry_delay_seconds * (2 ** (attempt - 1))
        jitter = random.uniform(0.0, 0.35)
        return min(base + jitter, 10.0)

    def _extract_generated_image(self, response: httpx.Response) -> bytes:
        """Parse Stable Diffusion JSON and decode base64 artifact."""

        try:
            payload = response.json()
        except ValueError as exc:
            raise AIEngineUpstreamError(
                "Stable Diffusion response is not valid JSON."
            ) from exc

        artifacts = payload.get("artifacts")
        if not artifacts or not isinstance(artifacts, list):
            raise AIEngineUpstreamError("Stable Diffusion response has no artifacts.")

        first_artifact = artifacts[0]
        if not isinstance(first_artifact, dict) or "base64" not in first_artifact:
            raise AIEngineUpstreamError("Stable Diffusion artifact has no base64 image data.")

        encoded_image = first_artifact["base64"]
        if not isinstance(encoded_image, str) or not encoded_image.strip():
            raise AIEngineUpstreamError("Stable Diffusion returned empty base64 image data.")

        try:
            return base64.b64decode(encoded_image, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise AIEngineUpstreamError(
                "Failed to decode Stable Diffusion base64 image data."
            ) from exc


def _detect_image_mime_type(image_bytes: bytes) -> tuple[str, str]:
    """Detect mime type by signature to avoid incorrect content-type uploads."""

    if image_bytes.startswith(b"\xFF\xD8\xFF"):
        return "image/jpeg", ".jpg"
    if image_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png", ".png"
    if len(image_bytes) >= 12 and image_bytes[:4] == b"RIFF" and image_bytes[8:12] == b"WEBP":
        return "image/webp", ".webp"

    raise AIEngineValidationError(
        "Unsupported image format. Allowed formats: JPEG, PNG, WEBP."
    )


def _extract_error_message(response: httpx.Response) -> str:
    """Extract a readable error message from upstream response payload."""

    try:
        payload = response.json()
    except ValueError:
        text = response.text.strip()
        return text[:500] if text else "No error details provided by upstream API."

    if isinstance(payload, dict):
        for key in ("message", "error", "detail"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()

    return "No structured error details provided by upstream API."


def _looks_like_moderation_error(status_code: int, message: str) -> bool:
    if status_code not in {400, 403, 422}:
        return False
    normalized = message.lower()
    return any(
        marker in normalized
        for marker in (
            "moderation",
            "content policy",
            "safety filter",
            "nsfw",
            "blocked prompt",
        )
    )


def _env_int(key: str, default: int) -> int:
    """Safe integer env parser with fallback and warning log."""

    raw_value = os.getenv(key)
    if raw_value is None:
        return default

    try:
        return int(raw_value)
    except ValueError:
        logger.warning("Invalid integer in %s=%s. Fallback to %s.", key, raw_value, default)
        return default


def _env_float(key: str, default: float) -> float:
    """Safe float env parser with fallback and warning log."""

    raw_value = os.getenv(key)
    if raw_value is None:
        return default

    try:
        return float(raw_value)
    except ValueError:
        logger.warning("Invalid float in %s=%s. Fallback to %s.", key, raw_value, default)
        return default


@dataclass(frozen=True, slots=True)
class MidjourneyTariffProfile:
    """Midjourney parameter profile derived from subscription tariff."""

    version: str
    quality: str
    stylize: int
    mode: Literal["fast", "relax"]
    provider: AIEngineProvider


def resolve_engine_for_tariff(
    subscription_status: SubscriptionStatus | str,
) -> MidjourneyTariffProfile:
    """Map user tariff to generation engine + Midjourney quality profile.

    Free users stay on Stable Diffusion (existing path).
    All paid commercial tariffs (Start / Pro / HalfYear / Year) use Midjourney.
    """

    normalized = (
        subscription_status.value
        if isinstance(subscription_status, SubscriptionStatus)
        else str(subscription_status).strip()
    )

    if normalized in SubscriptionStatus.paid_values():
        return MidjourneyTariffProfile(
            version="6",
            quality="2",
            stylize=250,
            mode="fast",
            provider=AIEngineProvider.MIDJOURNEY,
        )

    return MidjourneyTariffProfile(
        version="5.2",
        quality="1",
        stylize=100,
        mode="relax",
        provider=AIEngineProvider.STABLE_DIFFUSION,
    )


@dataclass(frozen=True, slots=True)
class MidjourneyConfig:
    """Runtime config for Midjourney Imagine API proxy."""

    api_key: str
    base_url: str = ""
    name: str = "legacy"
    authorization_scheme: Literal["bearer", "token", "api-key"] = "bearer"
    webhook_token: str = ""
    timeout_seconds: float = 180.0
    connect_timeout_seconds: float = 10.0
    max_connections: int = 100
    max_keepalive_connections: int = 40
    keepalive_expiry_seconds: float = 30.0
    max_parallel_requests: int = 50
    max_retries: int = 2
    base_retry_delay_seconds: float = 0.5
    poll_interval_seconds: float = 3.0
    max_poll_attempts: int = 60
    imagine_path: str = "/jobs/imagine"
    job_status_path_template: str = "/jobs/{job_id}"
    max_result_bytes: int = 30 * 1024 * 1024
    allowed_result_hosts: tuple[str, ...] = ()

    @classmethod
    def from_env(cls) -> "MidjourneyConfig":
        """Build Midjourney config from environment / Settings-compatible env vars.

        Required:
        - `MIDJOURNEY_API_KEY`

        Optional:
        - `MIDJOURNEY_BASE_URL`
        - `MIDJOURNEY_TIMEOUT_SECONDS`
        - `MIDJOURNEY_POLL_INTERVAL_SECONDS`
        - `MIDJOURNEY_MAX_POLL_ATTEMPTS`
        - `MIDJOURNEY_IMAGINE_PATH`
        - `MIDJOURNEY_JOB_STATUS_PATH_TEMPLATE`
        """

        api_key = os.getenv("MIDJOURNEY_API_KEY", "").strip()
        if not api_key:
            raise AIEngineConfigurationError(
                "Missing MIDJOURNEY_API_KEY environment variable."
            )

        return cls(
            api_key=api_key,
            base_url=os.getenv("MIDJOURNEY_BASE_URL", "").strip(),
            name=os.getenv("MIDJOURNEY_PROVIDER_NAME", "legacy").strip() or "legacy",
            webhook_token=os.getenv("MIDJOURNEY_WEBHOOK_TOKEN", "").strip(),
            timeout_seconds=_env_float("MIDJOURNEY_TIMEOUT_SECONDS", 180.0),
            connect_timeout_seconds=_env_float("MIDJOURNEY_CONNECT_TIMEOUT_SECONDS", 10.0),
            max_connections=_env_int("MIDJOURNEY_MAX_CONNECTIONS", 100),
            max_keepalive_connections=_env_int("MIDJOURNEY_MAX_KEEPALIVE_CONNECTIONS", 40),
            keepalive_expiry_seconds=_env_float("MIDJOURNEY_KEEPALIVE_EXPIRY_SECONDS", 30.0),
            max_parallel_requests=_env_int("MIDJOURNEY_MAX_PARALLEL_REQUESTS", 50),
            max_retries=_env_int("MIDJOURNEY_MAX_RETRIES", 2),
            base_retry_delay_seconds=_env_float("MIDJOURNEY_BASE_RETRY_DELAY_SECONDS", 0.5),
            poll_interval_seconds=_env_float("MIDJOURNEY_POLL_INTERVAL_SECONDS", 3.0),
            max_poll_attempts=_env_int("MIDJOURNEY_MAX_POLL_ATTEMPTS", 60),
            imagine_path=os.getenv("MIDJOURNEY_IMAGINE_PATH", "/jobs/imagine").strip(),
            job_status_path_template=os.getenv(
                "MIDJOURNEY_JOB_STATUS_PATH_TEMPLATE",
                "/jobs/{job_id}",
            ).strip(),
            max_result_bytes=_env_int(
                "GENERATION_MAX_RESULT_BYTES",
                30 * 1024 * 1024,
            ),
            allowed_result_hosts=tuple(
                host.strip().lower()
                for host in os.getenv("GENERATION_ALLOWED_RESULT_HOSTS", "").split(",")
                if host.strip()
            ),
        )

    @classmethod
    def from_settings(cls) -> "MidjourneyConfig":
        """Build the preserved synchronous adapter from central Settings."""

        settings = get_settings()
        api_key = (
            settings.midjourney_api_key.get_secret_value().strip()
            if settings.midjourney_api_key is not None
            else ""
        )
        if not api_key:
            raise AIEngineConfigurationError(
                "Missing MIDJOURNEY_API_KEY environment variable."
            )
        if not settings.midjourney_base_url.strip():
            raise AIEngineConfigurationError("MIDJOURNEY_BASE_URL must be configured.")
        return cls(
            api_key=api_key,
            base_url=settings.midjourney_base_url,
            webhook_token=settings.midjourney_webhook_token.get_secret_value(),
            timeout_seconds=settings.midjourney_timeout_seconds,
            poll_interval_seconds=settings.midjourney_poll_interval_seconds,
            max_poll_attempts=settings.midjourney_max_poll_attempts,
            max_result_bytes=settings.generation_max_result_bytes,
            allowed_result_hosts=tuple(settings.allowed_result_hosts),
        )


class MidjourneyService:
    """Async Midjourney client (Imagine + poll) for Pro-tier generation.

    Compatible with common Midjourney HTTP proxies that expose:
    1) POST imagine -> job_id
    2) GET job status -> image URL / base64 when completed
    """

    def __init__(self, config: MidjourneyConfig) -> None:
        if not config.base_url.strip():
            raise AIEngineConfigurationError("Midjourney base URL must not be empty.")
        if config.max_poll_attempts <= 0:
            raise AIEngineConfigurationError("max_poll_attempts must be greater than zero.")
        if config.poll_interval_seconds <= 0:
            raise AIEngineConfigurationError("poll_interval_seconds must be greater than zero.")
        if config.max_parallel_requests <= 0:
            raise AIEngineConfigurationError("max_parallel_requests must be greater than zero.")

        self._config = config
        self._semaphore = asyncio.Semaphore(config.max_parallel_requests)
        if config.authorization_scheme == "api-key":
            auth_headers = {"X-API-Key": config.api_key}
        elif config.authorization_scheme == "token":
            auth_headers = {"Authorization": f"Token {config.api_key}"}
        else:
            auth_headers = {"Authorization": f"Bearer {config.api_key}"}
        self._client = httpx.AsyncClient(
            base_url=config.base_url.rstrip("/"),
            headers={
                **auth_headers,
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
            timeout=httpx.Timeout(
                timeout=config.timeout_seconds,
                connect=config.connect_timeout_seconds,
            ),
            limits=httpx.Limits(
                max_connections=config.max_connections,
                max_keepalive_connections=config.max_keepalive_connections,
                keepalive_expiry=config.keepalive_expiry_seconds,
            ),
            http2=True,
        )

    @property
    def name(self) -> str:
        """Stable provider adapter name used by webhook routing."""

        return self._config.name

    @property
    def callback_token(self) -> str:
        """Secret token placed only in this provider's callback URL."""

        return self._config.webhook_token

    async def aclose(self) -> None:
        """Gracefully close underlying HTTP resources."""

        await self._client.aclose()

    async def generate_product_image(
        self,
        product_image: bytes,
        selected_style: str,
        user_text: str,
        tariff_profile: MidjourneyTariffProfile | None = None,
    ) -> bytes:
        """Generate product image via Midjourney Imagine API.

        Args:
            product_image: Source product image bytes (used as image prompt / reference).
            selected_style: Style descriptor.
            user_text: User instruction text.
            tariff_profile: Optional Pro/Free Midjourney parameter profile.
        """

        self._validate_input(
            product_image=product_image,
            selected_style=selected_style,
            user_text=user_text,
        )
        profile = tariff_profile or resolve_engine_for_tariff(SubscriptionStatus.PRO)
        prompt = self._build_prompt(
            selected_style=selected_style,
            user_text=user_text,
            profile=profile,
        )
        mime_type, _extension = _detect_image_mime_type(product_image)
        image_b64 = base64.b64encode(product_image).decode("ascii")

        async with self._semaphore:
            job_id = await self._submit_imagine(
                prompt=prompt,
                image_base64=image_b64,
                mime_type=mime_type,
                profile=profile,
            )
            image_bytes = await self._poll_job_until_ready(job_id)

        return image_bytes

    async def submit(
        self,
        *,
        product_image: bytes,
        selected_style: str,
        prompt: str,
        reply_url: str,
        reply_ref: str,
        render_mode: Literal["background_plate", "direct_vto"] = "background_plate",
    ) -> ProviderSubmission:
        """Submit one provider job and return without polling for its image."""

        self._validate_input(
            product_image=product_image,
            selected_style=selected_style,
            user_text=prompt,
        )
        if not reply_url.startswith(("https://", "http://")):
            raise AIEngineValidationError("reply_url must be an absolute HTTP(S) URL.")
        if not reply_ref.strip():
            raise AIEngineValidationError("reply_ref cannot be empty.")

        profile = resolve_engine_for_tariff(SubscriptionStatus.PRO)
        if render_mode == "direct_vto":
            provider_prompt = prompt.strip()
        else:
            provider_prompt = (
                f"{prompt.strip()} Generate a clean background plate for product compositing. "
                "Leave the central product area empty, preserve realistic light direction and "
                "ground plane, no text, no logos, no duplicate products."
            )
        merged_prompt = self._build_prompt(
            selected_style=selected_style,
            user_text=provider_prompt,
            profile=profile,
        )
        mime_type, _extension = _detect_image_mime_type(product_image)
        encoded = base64.b64encode(product_image).decode("ascii")
        async with self._semaphore:
            job_id = await self._submit_imagine(
                prompt=merged_prompt,
                image_base64=encoded,
                mime_type=mime_type,
                profile=profile,
                reply_url=reply_url,
                reply_ref=reply_ref,
            )
        return ProviderSubmission(
            provider=self.name,
            external_job_id=job_id,
            reply_ref=reply_ref,
            initial_status="created",
        )

    def verify_webhook(
        self,
        *,
        headers: Mapping[str, str],
        raw_body: bytes,
        callback_token: str | None,
    ) -> bool:
        """Accept a constant-time callback token or HMAC-SHA256 signature."""

        secret = self._config.webhook_token.strip()
        if not secret:
            return False
        if callback_token and hmac.compare_digest(callback_token, secret):
            return True
        header_token = str(headers.get("x-webhook-token") or "")
        if header_token and hmac.compare_digest(header_token, secret):
            return True
        supplied = str(headers.get("x-webhook-signature") or "")
        if supplied.startswith("sha256="):
            supplied = supplied[7:]
        if not supplied:
            return False
        expected = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(supplied, expected)

    def parse_webhook(self, payload: dict[str, Any]) -> ProviderWebhookEvent:
        """Normalise common provider callback shapes into a strict domain event."""

        external_job_id = _nested_string(
            payload,
            ("job_id", "jobId", "jobid", "task_id", "taskId", "id"),
        )
        reply_ref = _nested_string(payload, ("reply_ref", "replyRef", "reference"))
        status_value = _nested_string(payload, ("status", "state")) or "pending"
        if not reply_ref:
            raise AIEngineValidationError("Provider webhook has no reply_ref.")

        progress_raw = _nested_value(payload, ("progress", "percentage", "percent"))
        progress = _normalise_progress(progress_raw, status_value)
        result_url = _extract_result_url(payload)
        error_message = _nested_string(payload, ("error", "error_message", "message", "detail"))
        explicit_event_id = _nested_string(payload, ("event_id", "eventId", "delivery_id"))
        canonical = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
        payload_digest = hashlib.sha256(canonical).hexdigest()
        if explicit_event_id:
            # Some proxies reuse one event id for every progress update. Include
            # a payload digest so only byte-equivalent deliveries deduplicate.
            event_id = f"{explicit_event_id[:480]}:{payload_digest[:24]}"
        else:
            event_id = payload_digest
        validated_result_url = (
            TypeAdapter(HttpUrl).validate_python(result_url)
            if result_url is not None
            else None
        )
        return ProviderWebhookEvent(
            provider=self.name,
            event_id=event_id,
            external_job_id=external_job_id,
            reply_ref=reply_ref,
            status=status_value,
            progress=progress,
            result_url=validated_result_url,
            error_message=error_message,
            raw_payload=payload,
        )

    async def download_result(self, result_url: str) -> bytes:
        """Download a callback result with SSRF and response-size guards."""

        await _validate_public_result_url(
            result_url,
            allowed_hosts=frozenset(self._config.allowed_result_hosts),
        )
        try:
            async with self._client.stream("GET", result_url) as response:
                response.raise_for_status()
                declared_length = response.headers.get("Content-Length")
                if declared_length and int(declared_length) > self._config.max_result_bytes:
                    raise AIEngineUpstreamError("Provider result exceeds the configured limit.")
                content_type = response.headers.get("Content-Type", "").split(";", 1)[0]
                if content_type and content_type not in {
                    "image/png",
                    "image/jpeg",
                    "image/webp",
                    "application/octet-stream",
                }:
                    raise AIEngineUpstreamError(
                        f"Provider result has unsupported content type '{content_type}'."
                    )
                chunks: list[bytes] = []
                size = 0
                async for chunk in response.aiter_bytes():
                    size += len(chunk)
                    if size > self._config.max_result_bytes:
                        raise AIEngineUpstreamError(
                            "Provider result exceeds the configured limit."
                        )
                    chunks.append(chunk)
        except (httpx.HTTPError, ValueError) as exc:
            if isinstance(exc, AIEngineUpstreamError):
                raise
            raise AIEngineUpstreamError("Failed to download provider result.") from exc
        image_bytes = b"".join(chunks)
        if not image_bytes:
            raise AIEngineUpstreamError("Provider returned an empty result image.")
        _detect_image_mime_type(image_bytes)
        return image_bytes

    async def check_once(
        self,
        external_job_id: str,
        *,
        reply_ref: str,
    ) -> ProviderWebhookEvent | None:
        """Perform exactly one recovery request; never sleep or poll here."""

        path = self._config.job_status_path_template.format(job_id=external_job_id)
        try:
            response = await self._client.get(path)
            if response.status_code in TRANSIENT_HTTP_CODES:
                return None
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise AIEngineUpstreamError("Provider recovery status request failed.") from exc
        if not isinstance(payload, dict):
            raise AIEngineUpstreamError("Provider recovery response is not a JSON object.")
        if not _nested_string(payload, ("reply_ref", "replyRef", "reference")):
            payload = {**payload, "replyRef": reply_ref}
        return self.parse_webhook(payload)

    def _validate_input(self, product_image: bytes, selected_style: str, user_text: str) -> None:
        """Validate caller payload before external request."""

        if not isinstance(product_image, (bytes, bytearray)):
            raise AIEngineValidationError("product_image must be bytes.")
        if not product_image:
            raise AIEngineValidationError("product_image cannot be empty.")
        if not selected_style or not selected_style.strip():
            raise AIEngineValidationError("selected_style cannot be empty.")
        if not user_text or not user_text.strip():
            raise AIEngineValidationError("user_text cannot be empty.")

    def _build_prompt(
        self,
        selected_style: str,
        user_text: str,
        profile: MidjourneyTariffProfile,
    ) -> str:
        """Build Midjourney prompt with tariff-specific quality flags."""

        prompt_chunks = [
            user_text.strip(),
            f"style: {selected_style.strip()}",
            GOLDEN_PROMPT_SUFFIX,
            f"--v {profile.version}",
            f"--q {profile.quality}",
            f"--stylize {profile.stylize}",
        ]
        if profile.mode == "relax":
            prompt_chunks.append("--relax")
        return " ".join(prompt_chunks)

    async def _submit_imagine(
        self,
        prompt: str,
        image_base64: str,
        mime_type: str,
        profile: MidjourneyTariffProfile,
        reply_url: str | None = None,
        reply_ref: str | None = None,
    ) -> str:
        """Submit Imagine job and return upstream job id."""

        payload: dict[str, Any] = {
            "prompt": prompt,
            "image": f"data:{mime_type};base64,{image_base64}",
            "mode": profile.mode,
        }
        if reply_url is not None and reply_ref is not None:
            payload.update(
                {
                    "stream": False,
                    "replyUrl": reply_url,
                    "replyRef": reply_ref,
                    "replyLevel": "all",
                }
            )

        max_attempts = self._config.max_retries + 1
        last_error: Exception | None = None

        for attempt in range(1, max_attempts + 1):
            try:
                response = await self._client.post(self._config.imagine_path, json=payload)

                if response.status_code in TRANSIENT_HTTP_CODES and attempt < max_attempts:
                    await asyncio.sleep(self._compute_retry_delay(attempt, response))
                    continue

                if response.is_error:
                    error_message = _extract_error_message(response)
                    if response.status_code == 429:
                        raise AIEngineRateLimitError(
                            f"Midjourney provider rate limit reached: {error_message}"
                        )
                    if _looks_like_moderation_error(
                        response.status_code,
                        error_message,
                    ):
                        raise AIEngineModerationError(
                            "Midjourney provider rejected the request under its content policy."
                        )
                    raise AIEngineUpstreamError(
                        f"Midjourney Imagine API returned {response.status_code}: "
                        f"{error_message}"
                    )

                job_id = self._extract_job_id(response)
                if not job_id:
                    raise AIEngineUpstreamError("Midjourney Imagine response has no job id.")
                return job_id

            except (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError) as exc:
                last_error = exc
                if attempt >= max_attempts:
                    break
                await asyncio.sleep(self._compute_retry_delay(attempt, response=None))

        raise AIEngineUpstreamError(
            "Midjourney Imagine API is temporarily unavailable after retries."
        ) from last_error

    async def _poll_job_until_ready(self, job_id: str) -> bytes:
        """Poll job status until image is ready or attempts are exhausted.

        Note: Celery/webhook-based waiting will replace polling in a later sprint.
        This poll loop is the baseline for synchronous Pro generation.
        """

        status_path = self._config.job_status_path_template.format(job_id=job_id)

        for attempt in range(1, self._config.max_poll_attempts + 1):
            try:
                response = await self._client.get(status_path)
            except (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError) as exc:
                if attempt >= self._config.max_poll_attempts:
                    raise AIEngineUpstreamError(
                        "Midjourney job polling failed due to network errors."
                    ) from exc
                await asyncio.sleep(self._config.poll_interval_seconds)
                continue

            if response.status_code in TRANSIENT_HTTP_CODES:
                await asyncio.sleep(self._config.poll_interval_seconds)
                continue

            if response.is_error:
                raise AIEngineUpstreamError(
                    f"Midjourney job status returned {response.status_code}: "
                    f"{_extract_error_message(response)}"
                )

            status, image_payload = self._parse_job_payload(response)
            normalized_status = status.lower()

            if normalized_status == "moderated":
                raise AIEngineModerationError(
                    "Midjourney job was rejected under the provider content policy."
                )
            if normalized_status in {"failed", "error", "cancelled"}:
                raise AIEngineUpstreamError(f"Midjourney job failed with status '{status}'.")

            if normalized_status in {"completed", "done", "success", "finished"} and image_payload:
                return await self._resolve_image_bytes(image_payload)

            await asyncio.sleep(self._config.poll_interval_seconds)

        raise AIEngineUpstreamError(
            f"Midjourney job {job_id} did not complete within "
            f"{self._config.max_poll_attempts} poll attempts."
        )

    def _extract_job_id(self, response: httpx.Response) -> str | None:
        """Extract job id from common Midjourney proxy response shapes."""

        try:
            payload = response.json()
        except ValueError:
            return None

        if not isinstance(payload, dict):
            return None

        for key in ("job_id", "jobId", "jobid", "id", "task_id", "taskId"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()

        data = payload.get("data")
        if isinstance(data, dict):
            for key in ("job_id", "jobId", "jobid", "id", "task_id", "taskId"):
                value = data.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()

        return None

    def _parse_job_payload(self, response: httpx.Response) -> tuple[str, str | None]:
        """Parse status + image reference (URL or base64) from job payload."""

        try:
            payload = response.json()
        except ValueError as exc:
            raise AIEngineUpstreamError("Midjourney job status is not valid JSON.") from exc

        if not isinstance(payload, dict):
            raise AIEngineUpstreamError("Midjourney job status has unexpected shape.")

        status = payload.get("status") or payload.get("state") or "pending"
        if not isinstance(status, str):
            status = "pending"

        image_payload: str | None = None
        for key in ("image_base64", "base64", "image_url", "imageUrl", "url", "cdn_url"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                image_payload = value.strip()
                break

        if image_payload is None:
            attachments = payload.get("attachments") or payload.get("images") or payload.get("output")
            if isinstance(attachments, list) and attachments:
                first = attachments[0]
                if isinstance(first, str) and first.strip():
                    image_payload = first.strip()
                elif isinstance(first, dict):
                    for key in ("url", "image_url", "base64", "image_base64"):
                        value = first.get(key)
                        if isinstance(value, str) and value.strip():
                            image_payload = value.strip()
                            break

        return status, image_payload

    async def _resolve_image_bytes(self, image_payload: str) -> bytes:
        """Decode base64 image data or download from CDN URL."""

        if image_payload.startswith("data:") and "," in image_payload:
            _header, encoded = image_payload.split(",", 1)
            try:
                return base64.b64decode(encoded, validate=True)
            except (binascii.Error, ValueError) as exc:
                raise AIEngineUpstreamError(
                    "Failed to decode Midjourney data-URI image."
                ) from exc

        # Heuristic: long payload without scheme is treated as raw base64.
        if "://" not in image_payload and len(image_payload) > 256:
            try:
                return base64.b64decode(image_payload, validate=True)
            except (binascii.Error, ValueError) as exc:
                raise AIEngineUpstreamError(
                    "Failed to decode Midjourney base64 image data."
                ) from exc

        try:
            response = await self._client.get(image_payload)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise AIEngineUpstreamError(
                "Failed to download Midjourney result image from CDN URL."
            ) from exc

        if not response.content:
            raise AIEngineUpstreamError("Midjourney CDN returned empty image body.")
        return response.content

    def _compute_retry_delay(self, attempt: int, response: httpx.Response | None) -> float:
        """Compute retry delay with Retry-After support and jitter."""

        if response is not None:
            retry_after = response.headers.get("Retry-After")
            if retry_after:
                try:
                    parsed_retry_after = float(retry_after)
                    if parsed_retry_after > 0:
                        return min(parsed_retry_after, 15.0)
                except ValueError:
                    logger.debug("Non-numeric Retry-After header ignored: %s", retry_after)

        base = self._config.base_retry_delay_seconds * (2 ** (attempt - 1))
        jitter = random.uniform(0.0, 0.4)
        return min(base + jitter, 15.0)


def _nested_value(payload: dict[str, Any], keys: tuple[str, ...]) -> Any:
    """Read common values from root or known provider envelope objects."""

    for key in keys:
        if key in payload:
            return payload[key]
    for container_key in ("response", "data", "job", "request", "result"):
        nested = payload.get(container_key)
        if isinstance(nested, dict):
            value = _nested_value(nested, keys)
            if value is not None:
                return value
    return None


def _nested_string(payload: dict[str, Any], keys: tuple[str, ...]) -> str | None:
    value = _nested_value(payload, keys)
    if isinstance(value, (str, int)) and str(value).strip():
        return str(value).strip()
    return None


def _normalise_progress(value: Any, status_value: str) -> int:
    if isinstance(value, str):
        value = value.strip().rstrip("%")
    try:
        progress = int(float(value))
    except (TypeError, ValueError):
        progress = 100 if status_value.lower() in {"completed", "done", "success"} else 0
    return max(0, min(progress, 100))


def _extract_result_url(payload: dict[str, Any]) -> str | None:
    direct = _nested_string(
        payload,
        ("image_url", "imageUrl", "cdn_url", "result_url", "resultUrl", "url"),
    )
    if direct and direct.startswith(("https://", "http://")):
        return direct
    for container_key in ("attachments", "images", "output", "outputs"):
        container = _nested_value(payload, (container_key,))
        if not isinstance(container, list):
            continue
        for item in container:
            if isinstance(item, str) and item.startswith(("https://", "http://")):
                return item
            if isinstance(item, dict):
                candidate = _nested_string(
                    item,
                    ("url", "image_url", "imageUrl", "cdn_url"),
                )
                if candidate and candidate.startswith(("https://", "http://")):
                    return candidate
    return None


async def _validate_public_result_url(
    result_url: str,
    *,
    allowed_hosts: frozenset[str],
) -> None:
    parsed = urlparse(result_url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise AIEngineValidationError("Provider result URL must use HTTPS.")
    if parsed.username or parsed.password or parsed.port not in {None, 443}:
        raise AIEngineValidationError("Provider result URL contains forbidden authority data.")
    hostname = parsed.hostname.lower().rstrip(".")
    if allowed_hosts and not any(
        hostname == allowed or hostname.endswith(f".{allowed}")
        for allowed in allowed_hosts
    ):
        raise AIEngineValidationError("Provider result host is not allowlisted.")

    try:
        address_info = await asyncio.to_thread(
            socket.getaddrinfo,
            hostname,
            443,
            type=socket.SOCK_STREAM,
        )
    except OSError as exc:
        raise AIEngineUpstreamError("Provider result host cannot be resolved.") from exc
    for address in address_info:
        ip = ipaddress.ip_address(address[4][0])
        if not ip.is_global:
            raise AIEngineValidationError(
                "Provider result URL resolves to a private or reserved address."
            )


class StableDiffusionImmediateAdapter:
    """Application port adapter around the preserved Stable Diffusion client."""

    @property
    def name(self) -> str:
        return AIEngineProvider.STABLE_DIFFUSION.value

    async def generate(
        self,
        *,
        product_image: bytes,
        selected_style: str,
        prompt: str,
    ) -> bytes:
        return await get_ai_engine().generate_product_image(
            product_image=product_image,
            selected_style=selected_style,
            user_text=prompt,
        )

    async def inpaint_edges(
        self,
        *,
        composited_image: bytes,
        edge_mask: bytes,
        prompt: str,
    ) -> bytes:
        return await get_ai_engine().inpaint_product_edges(
            composited_image=composited_image,
            edge_mask=edge_mask,
            prompt=prompt,
        )


# Lazy singletons for app-wide reuse.
_default_service: StableDiffusionService | None = None
_midjourney_service: MidjourneyService | None = None
_async_midjourney_services: dict[str, MidjourneyService] | None = None
_stable_immediate_adapter = StableDiffusionImmediateAdapter()


def get_ai_engine() -> StableDiffusionService:
    """Get singleton StableDiffusionService configured from environment.

    Preserved for backward compatibility with series_generator and callers
    that expect the original Stable Diffusion engine.
    """

    global _default_service
    if _default_service is None:
        _default_service = StableDiffusionService(StableDiffusionConfig.from_settings())
    return _default_service


def get_midjourney_engine() -> MidjourneyService:
    """Get singleton MidjourneyService configured from environment."""

    global _midjourney_service
    if _midjourney_service is None:
        _midjourney_service = MidjourneyService(MidjourneyConfig.from_settings())
    return _midjourney_service


def get_async_midjourney_providers() -> tuple[MidjourneyService, ...]:
    """Build provider-neutral webhook adapters from strict Settings JSON."""

    global _async_midjourney_services
    if _async_midjourney_services is None:
        settings = get_settings()
        services: dict[str, MidjourneyService] = {}
        reply_secret = settings.midjourney_reply_ref_secret.get_secret_value().strip()
        shared_webhook_token = (
            settings.midjourney_webhook_token.get_secret_value().strip()
        )
        for provider in settings.midjourney_providers:
            if provider.name in services:
                raise AIEngineConfigurationError(
                    f"Duplicate Midjourney provider name '{provider.name}'."
                )
            provider_token = (
                provider.webhook_token.get_secret_value().strip()
                if provider.webhook_token is not None
                else shared_webhook_token
            )
            if not provider_token or not (reply_secret or shared_webhook_token):
                logger.error(
                    "Skipping async provider '%s': webhook token and reply-ref secret "
                    "must be configured.",
                    provider.name,
                )
                continue
            services[provider.name] = MidjourneyService(
                MidjourneyConfig(
                    name=provider.name,
                    api_key=provider.api_key.get_secret_value(),
                    base_url=provider.base_url,
                    authorization_scheme=provider.authorization_scheme,
                    webhook_token=provider_token,
                    timeout_seconds=settings.midjourney_timeout_seconds,
                    poll_interval_seconds=settings.midjourney_poll_interval_seconds,
                    max_poll_attempts=settings.midjourney_max_poll_attempts,
                    imagine_path=provider.imagine_path,
                    job_status_path_template=provider.status_path_template,
                    max_result_bytes=settings.generation_max_result_bytes,
                    allowed_result_hosts=tuple(settings.allowed_result_hosts),
                )
            )
        _async_midjourney_services = services
    return tuple(_async_midjourney_services.values())


def get_async_midjourney_provider(name: str) -> MidjourneyService | None:
    """Resolve a configured webhook adapter by its public route name."""

    return next(
        (provider for provider in get_async_midjourney_providers() if provider.name == name),
        None,
    )


async def get_healthy_async_midjourney_providers(
    *,
    exclude: frozenset[str] = frozenset(),
) -> tuple[MidjourneyService, ...]:
    """Return configured providers whose Redis circuit is currently closed."""

    providers: list[MidjourneyService] = []
    for provider in get_async_midjourney_providers():
        if provider.name in exclude:
            continue
        if not await is_provider_circuit_open(provider.name):
            providers.append(provider)
    return tuple(providers)


def get_stable_diffusion_adapter() -> StableDiffusionImmediateAdapter:
    """Return the immediate fallback provider adapter."""

    return _stable_immediate_adapter


async def note_provider_success(provider_name: str) -> None:
    await record_provider_success(provider_name)


async def note_provider_failure(provider_name: str) -> None:
    await record_provider_failure(provider_name)


def get_midjourney_callback_token(provider_name: str) -> str:
    provider = get_async_midjourney_provider(provider_name)
    if provider is None:
        return ""
    return provider.callback_token


async def close_ai_engine() -> None:
    """Close singleton service resources (call during app shutdown)."""

    global _default_service, _midjourney_service, _async_midjourney_services
    if _default_service is not None:
        await _default_service.aclose()
        _default_service = None
    if _midjourney_service is not None:
        await _midjourney_service.aclose()
        _midjourney_service = None
    if _async_midjourney_services is not None:
        await asyncio.gather(
            *(service.aclose() for service in _async_midjourney_services.values()),
            return_exceptions=True,
        )
        _async_midjourney_services = None


async def generate_product_image(
    product_image: bytes,
    selected_style: str,
    user_text: str,
) -> bytes:
    """Convenience function required by the project task.

    This wrapper delegates to the singleton Stable Diffusion service instance
    (original behavior preserved).
    """

    service = get_ai_engine()
    return await service.generate_product_image(
        product_image=product_image,
        selected_style=selected_style,
        user_text=user_text,
    )


async def generate_product_image_for_tariff(
    product_image: bytes,
    selected_style: str,
    user_text: str,
    subscription_status: SubscriptionStatus | str = SubscriptionStatus.FREE,
) -> bytes:
    """Generate product image using the engine selected by user tariff.

    - Free: Stable Diffusion (existing high-load path)
    - Pro: Midjourney with premium parameter profile

    If Midjourney is selected but not configured, falls back to Stable Diffusion
    with a warning log so Free/dev environments keep working.
    """

    profile = resolve_engine_for_tariff(subscription_status)

    if profile.provider == AIEngineProvider.MIDJOURNEY:
        try:
            midjourney = get_midjourney_engine()
            return await midjourney.generate_product_image(
                product_image=product_image,
                selected_style=selected_style,
                user_text=user_text,
                tariff_profile=profile,
            )
        except (AIEngineConfigurationError, AIEngineUpstreamError) as exc:
            logger.warning(
                "Midjourney unavailable for paid tariff (%s). Falling back to Stable Diffusion.",
                exc,
            )

    return await generate_product_image(
        product_image=product_image,
        selected_style=selected_style,
        user_text=user_text,
    )
