"""Provider interfaces kept free of FastAPI, Celery, Redis, and SQLAlchemy."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal, Protocol, runtime_checkable

from app.domain.generation import (
    GenerationEngineMode,
    ProviderSubmission,
    ProviderWebhookEvent,
)


@runtime_checkable
class AsyncImageProviderPort(Protocol):
    """Submit-only provider completed later through a webhook."""

    @property
    def name(self) -> str:
        """Stable adapter name used in callback routes and attempts."""

    async def submit(
        self,
        *,
        product_image: bytes,
        selected_style: str,
        prompt: str,
        reply_url: str,
        reply_ref: str,
        render_mode: Literal["background_plate", "direct_vto"] = "background_plate",
        engine_mode: GenerationEngineMode = GenerationEngineMode.STANDARD,
    ) -> ProviderSubmission:
        """Submit work and return immediately after receiving an upstream id."""

    def verify_webhook(
        self,
        *,
        headers: Mapping[str, str],
        raw_body: bytes,
        callback_token: str | None,
    ) -> bool:
        """Verify callback authenticity before parsing it."""

    def parse_webhook(self, payload: dict[str, Any]) -> ProviderWebhookEvent:
        """Normalise a provider-specific callback."""

    async def download_result(self, result_url: str) -> bytes:
        """Download a bounded, allowlisted result after callback completion."""

    async def check_once(
        self,
        external_job_id: str,
        *,
        reply_ref: str,
    ) -> ProviderWebhookEvent | None:
        """Perform one recovery status request, never a resident poll loop."""

    async def aclose(self) -> None:
        """Release network resources."""


@runtime_checkable
class ImmediateImageProviderPort(Protocol):
    """Provider returning image bytes in one bounded async request."""

    @property
    def name(self) -> str:
        """Stable adapter name."""

    async def generate(
        self,
        *,
        product_image: bytes,
        selected_style: str,
        prompt: str,
    ) -> bytes:
        """Generate an image in one bounded asynchronous operation."""
