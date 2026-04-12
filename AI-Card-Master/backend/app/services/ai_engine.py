"""High-load Stable Diffusion service client.

This module provides an async service that sends product images to the
Stable Diffusion API (image-to-image flow) and returns generated image bytes.

Key features:
- async requests via httpx with connection pooling;
- retry strategy for transient upstream failures;
- automatic "golden prompt" enrichment;
- hidden negative prompt for artifact suppression;
- strict input validation and explicit error contracts.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import logging
import os
import random
from dataclasses import dataclass
from typing import Final

import httpx


logger = logging.getLogger(__name__)


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

                raise AIEngineUpstreamError(
                    f"Stable Diffusion API returned {status_code}: "
                    f"{_extract_error_message(exc.response)}"
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


# Lazy singleton for app-wide reuse.
_default_service: StableDiffusionService | None = None


def get_ai_engine() -> StableDiffusionService:
    """Get singleton StableDiffusionService configured from environment."""

    global _default_service
    if _default_service is None:
        _default_service = StableDiffusionService(StableDiffusionConfig.from_env())
    return _default_service


async def close_ai_engine() -> None:
    """Close singleton service resources (call during app shutdown)."""

    global _default_service
    if _default_service is not None:
        await _default_service.aclose()
        _default_service = None


async def generate_product_image(
    product_image: bytes,
    selected_style: str,
    user_text: str,
) -> bytes:
    """Convenience function required by the project task.

    This wrapper delegates to the singleton high-load service instance.
    """

    service = get_ai_engine()
    return await service.generate_product_image(
        product_image=product_image,
        selected_style=selected_style,
        user_text=user_text,
    )
