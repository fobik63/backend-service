"""Failover wrapper: primary 3D engine with optional secondary provider."""

from __future__ import annotations

import logging
from typing import Any

from app.services.three_d.base import BaseThreeDEngine
from app.services.three_d.dto import ThreeDTaskStatusDTO
from app.services.three_d.errors import (
    THREE_D_UNAVAILABLE_MESSAGE,
    ThreeDServiceUnavailableError,
)

logger = logging.getLogger(__name__)

_PRIMARY_PREFIX = "p"
_FALLBACK_PREFIX = "f"


class FailoverThreeDEngine(BaseThreeDEngine):
    """Route create/status/cancel across primary + optional backup engine.

    When the primary circuit is OPEN (``ThreeDServiceUnavailableError``),
    ``create_generation_task`` silently switches to ``fallback``. Provider task
    ids are tagged ``p:`` / ``f:`` so later polls hit the engine that created
    them. If both are unavailable, raises ``ThreeDServiceUnavailableError``.
    """

    def __init__(
        self,
        primary: BaseThreeDEngine,
        fallback: BaseThreeDEngine | None = None,
        *,
        primary_name: str = "primary",
        fallback_name: str = "fallback",
    ) -> None:
        self._primary = primary
        self._fallback = fallback
        self._primary_name = primary_name
        self._fallback_name = fallback_name

    async def ensure_available(self) -> None:
        try:
            await self._primary.ensure_available()
            return
        except ThreeDServiceUnavailableError:
            if self._fallback is None:
                raise
        try:
            await self._fallback.ensure_available()
        except ThreeDServiceUnavailableError as exc:
            raise ThreeDServiceUnavailableError(THREE_D_UNAVAILABLE_MESSAGE) from exc

    async def aclose(self) -> None:
        """Close primary and fallback adapters (owned httpx clients)."""

        for engine in (self._primary, self._fallback):
            if engine is None:
                continue
            try:
                await engine.aclose()
            except Exception:
                logger.exception(
                    "Failed to close 3D adapter during FailoverThreeDEngine.aclose"
                )

    async def create_generation_task(
        self,
        prompt: str,
        image_url: str | None,
        params: dict[str, Any],
    ) -> str:
        try:
            task_id = await self._primary.create_generation_task(
                prompt, image_url, params
            )
            return _tag(_PRIMARY_PREFIX, task_id) if self._fallback else task_id
        except ThreeDServiceUnavailableError:
            if self._fallback is None:
                raise
            logger.warning(
                "3D primary provider '%s' unavailable; failing over to '%s'",
                self._primary_name,
                self._fallback_name,
            )
            try:
                task_id = await self._fallback.create_generation_task(
                    prompt, image_url, params
                )
            except ThreeDServiceUnavailableError as exc:
                raise ThreeDServiceUnavailableError(THREE_D_UNAVAILABLE_MESSAGE) from exc
            return _tag(_FALLBACK_PREFIX, task_id)

    async def get_task_status(self, provider_task_id: str) -> ThreeDTaskStatusDTO:
        engine, raw_id = self._route(provider_task_id)
        return await engine.get_task_status(raw_id)

    async def cancel_task(self, provider_task_id: str) -> bool:
        engine, raw_id = self._route(provider_task_id)
        return await engine.cancel_task(raw_id)

    def _route(self, provider_task_id: str) -> tuple[BaseThreeDEngine, str]:
        prefix, raw = _split_tag(provider_task_id)
        if prefix == _FALLBACK_PREFIX:
            if self._fallback is None:
                raise ThreeDServiceUnavailableError(
                    "Fallback 3D provider is not configured for this task."
                )
            return self._fallback, raw
        if prefix == _PRIMARY_PREFIX or prefix is None:
            return self._primary, raw
        # Unknown tag — treat as opaque primary id (legacy / single-provider).
        return self._primary, provider_task_id.strip()


def _tag(prefix: str, task_id: str) -> str:
    return f"{prefix}:{task_id}"


def _split_tag(provider_task_id: str) -> tuple[str | None, str]:
    cleaned = provider_task_id.strip()
    if not cleaned:
        return None, cleaned
    if cleaned.startswith(f"{_PRIMARY_PREFIX}:") or cleaned.startswith(
        f"{_FALLBACK_PREFIX}:"
    ):
        prefix, _, rest = cleaned.partition(":")
        return prefix, rest
    return None, cleaned
