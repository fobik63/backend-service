"""Meshy API v2 adapter (text-to-3d / image-to-3d)."""

from __future__ import annotations

import logging
import re
from typing import Any
from urllib.parse import urlparse

import httpx

from app.application.ports.circuit_breaker import CircuitBreakerPort
from app.domain.circuit_breaker import CIRCUIT_MESHY, is_trip_worthy_status
from app.infrastructure.circuit_breaker.guard import (
    CircuitBreakerOpenError,
    execute_with_circuit_breaker,
)
from app.services.three_d.base import BaseThreeDEngine
from app.services.three_d.dto import (
    ThreeDGenerationStage,
    ThreeDTaskLifecycleStatus,
    ThreeDTaskStatusDTO,
)
from app.services.three_d.errors import (
    THREE_D_UNAVAILABLE_MESSAGE,
    ThreeDServiceUnavailableError,
)

logger = logging.getLogger(__name__)

_MESHY_STATUS_MAP: dict[str, ThreeDTaskLifecycleStatus] = {
    "PENDING": ThreeDTaskLifecycleStatus.QUEUED,
    "IN_PROGRESS": ThreeDTaskLifecycleStatus.PROCESSING,
    "SUCCEEDED": ThreeDTaskLifecycleStatus.COMPLETED,
    "FAILED": ThreeDTaskLifecycleStatus.FAILED,
    "CANCELED": ThreeDTaskLifecycleStatus.FAILED,
    "CANCELLED": ThreeDTaskLifecycleStatus.FAILED,
}

_DEFAULT_HOST = "https://api.meshy.ai"
_HTTP_STATUS_RE = re.compile(r"HTTP (\d{3})")


class MeshyEngineError(RuntimeError):
    """Raised when Meshy HTTP API returns an unexpected error."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class MeshyEngineAdapter(BaseThreeDEngine):
    """``BaseThreeDEngine`` backed by Meshy ``POST/GET /v2/text-to-3d``.

    Image inputs are routed to ``/v1/image-to-3d``. Returned provider ids for
    image jobs are prefixed with ``i2d:`` so status/cancel hit the right path.

    Outbound HTTP is guarded by the shared Redis CircuitBreaker: after
    ``failure_threshold`` trip-worthy responses (429/5xx/timeouts) the circuit
    opens and callers receive ``ThreeDServiceUnavailableError``.
    """

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = "https://api.meshy.ai/v2",
        timeout_seconds: float = 60.0,
        client: httpx.AsyncClient | None = None,
        circuit_breaker: CircuitBreakerPort | None = None,
    ) -> None:
        key = api_key.strip()
        if not key:
            raise ValueError("MeshyEngineAdapter requires a non-empty api_key.")
        configured = base_url.strip().rstrip("/")
        if not configured:
            raise ValueError("MeshyEngineAdapter requires a non-empty base_url.")

        self._api_key = key
        self._text_to_3d_base = configured
        self._api_host = _host_root(configured)
        self._timeout = httpx.Timeout(timeout_seconds)
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            timeout=self._timeout,
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )
        self._circuit_name = CIRCUIT_MESHY
        # None disables the breaker (unit tests); production factory injects Redis CB.
        self._circuit_breaker: CircuitBreakerPort | None = circuit_breaker

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def ensure_available(self) -> None:
        if self._circuit_breaker is None:
            return
        if await self._circuit_breaker.is_open(self._circuit_name):
            raise ThreeDServiceUnavailableError(THREE_D_UNAVAILABLE_MESSAGE)

    async def create_generation_task(
        self,
        prompt: str,
        image_url: str | None,
        params: dict[str, Any],
    ) -> str:
        cleaned_image = image_url.strip() if image_url and image_url.strip() else None
        cleaned_prompt = prompt.strip()
        if cleaned_image is None and not cleaned_prompt:
            raise ValueError("prompt must be a non-empty string when image_url is absent.")

        if cleaned_image is not None:
            return await self._create_image_to_3d(cleaned_image, cleaned_prompt, params)

        payload = self._build_text_to_3d_payload(cleaned_prompt, params)
        data = await self._request_json(
            "POST",
            f"{self._text_to_3d_base}/text-to-3d",
            json=payload,
        )
        task_id = _extract_meshy_task_id(data)
        if not task_id:
            raise MeshyEngineError(f"Meshy create response missing task id: {data!r}")
        return task_id

    async def get_task_status(self, provider_task_id: str) -> ThreeDTaskStatusDTO:
        task_id = provider_task_id.strip()
        if not task_id:
            raise ValueError("provider_task_id must be a non-empty string.")

        route_prefix, raw_id = _split_route_prefix(task_id)
        if route_prefix == "i2d":
            data = await self._request_json(
                "GET",
                f"{self._api_host}/v1/image-to-3d/{raw_id}",
            )
        else:
            try:
                data = await self._request_json(
                    "GET",
                    f"{self._text_to_3d_base}/text-to-3d/{raw_id}",
                )
            except MeshyEngineError as exc:
                if "HTTP 404" not in str(exc):
                    raise
                data = await self._request_json(
                    "GET",
                    f"{self._api_host}/v1/image-to-3d/{raw_id}",
                )

        return self._to_dto(data, provider_task_id=task_id)

    async def cancel_task(self, provider_task_id: str) -> bool:
        task_id = provider_task_id.strip()
        if not task_id:
            return False

        route_prefix, raw_id = _split_route_prefix(task_id)
        if route_prefix == "i2d":
            attempts = (
                ("POST", f"{self._api_host}/v1/image-to-3d/{raw_id}/cancel"),
                ("DELETE", f"{self._api_host}/v1/image-to-3d/{raw_id}"),
            )
        else:
            attempts = (
                ("POST", f"{self._text_to_3d_base}/text-to-3d/{raw_id}/cancel"),
                ("DELETE", f"{self._text_to_3d_base}/text-to-3d/{raw_id}"),
            )

        for method, url in attempts:
            try:
                response = await self._client.request(method, url)
            except httpx.HTTPError as exc:
                logger.warning("Meshy cancel %s %s failed: %s", method, url, exc)
                continue
            if response.status_code in {200, 202, 204}:
                return True
            if response.status_code in {404, 409, 422}:
                return False
            logger.warning(
                "Meshy cancel %s %s returned HTTP %s: %s",
                method,
                url,
                response.status_code,
                response.text[:300],
            )
        return False

    async def _create_image_to_3d(
        self,
        image_url: str,
        prompt: str,
        params: dict[str, Any],
    ) -> str:
        payload: dict[str, Any] = {"image_url": image_url}
        if prompt:
            payload["prompt"] = prompt[:600]
        for key in (
            "ai_model",
            "topology",
            "target_polycount",
            "should_remesh",
            "enable_pbr",
            "texture_resolution",
            "target_formats",
            "moderation",
        ):
            if key in params:
                payload[key] = params[key]
        if "polycount_target" in params and "target_polycount" not in payload:
            payload["target_polycount"] = params["polycount_target"]

        data = await self._request_json(
            "POST",
            f"{self._api_host}/v1/image-to-3d",
            json=payload,
        )
        task_id = _extract_meshy_task_id(data)
        if not task_id:
            raise MeshyEngineError(f"Meshy image-to-3d response missing task id: {data!r}")
        return f"i2d:{task_id}"

    @staticmethod
    def _build_text_to_3d_payload(prompt: str, params: dict[str, Any]) -> dict[str, Any]:
        mode = str(params.get("mode", "preview")).strip().lower() or "preview"
        payload: dict[str, Any] = {
            "mode": mode,
            "prompt": prompt[:600],
        }
        if mode == "refine":
            preview_id = params.get("preview_task_id")
            if not preview_id or not str(preview_id).strip():
                raise ValueError("refine mode requires params['preview_task_id'].")
            payload["preview_task_id"] = str(preview_id).strip()

        optional_keys = (
            "model_type",
            "ai_model",
            "should_remesh",
            "topology",
            "target_polycount",
            "decimation_mode",
            "pose_mode",
            "art_style",
            "moderation",
            "target_formats",
            "alpha_thumbnail",
            "auto_size",
            "origin_at",
            "enable_pbr",
            "texture_resolution",
        )
        for key in optional_keys:
            if key in params:
                payload[key] = params[key]
        if "polycount_target" in params and "target_polycount" not in payload:
            payload["target_polycount"] = params["polycount_target"]
        if "format" in params and "target_formats" not in payload:
            fmt = str(params["format"]).strip().lower()
            if fmt:
                payload["target_formats"] = [fmt]
        return payload

    async def _request_json(
        self,
        method: str,
        url: str,
        *,
        json: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        async def _primary() -> dict[str, Any]:
            return await self._request_json_raw(method, url, json=json)

        if self._circuit_breaker is None:
            return await _primary()

        try:
            return await execute_with_circuit_breaker(
                breaker=self._circuit_breaker,
                circuit_name=self._circuit_name,
                primary=_primary,
                fallback=None,
                is_trip_worthy_exc=_is_trip_worthy_meshy_exc,
            )
        except CircuitBreakerOpenError as exc:
            raise ThreeDServiceUnavailableError(THREE_D_UNAVAILABLE_MESSAGE) from exc

    async def _request_json_raw(
        self,
        method: str,
        url: str,
        *,
        json: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            response = await self._client.request(method, url, json=json)
        except httpx.TimeoutException as exc:
            raise MeshyEngineError(
                f"Meshy request timed out: {method} {url}",
                status_code=None,
            ) from exc
        except httpx.HTTPError as exc:
            raise MeshyEngineError(
                f"Meshy transport error: {exc}",
                status_code=None,
            ) from exc

        if response.status_code >= 400:
            raise MeshyEngineError(
                f"Meshy HTTP {response.status_code} for {method} {url}: "
                f"{response.text[:500]}",
                status_code=response.status_code,
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise MeshyEngineError("Meshy returned non-JSON body.") from exc
        if not isinstance(payload, dict):
            raise MeshyEngineError(
                f"Meshy JSON root must be an object, got {type(payload)!r}"
            )
        return payload

    @classmethod
    def _to_dto(cls, data: dict[str, Any], *, provider_task_id: str) -> ThreeDTaskStatusDTO:
        raw_status = str(data.get("status") or "PENDING").strip().upper()
        status = _MESHY_STATUS_MAP.get(raw_status, ThreeDTaskLifecycleStatus.PROCESSING)
        progress = _clamp_progress(data.get("progress", 0))
        stage = (
            _stage_for_progress(progress)
            if status is ThreeDTaskLifecycleStatus.PROCESSING
            else None
        )

        error_message: str | None = None
        task_error = data.get("task_error")
        if isinstance(task_error, dict):
            msg = task_error.get("message")
            if isinstance(msg, str) and msg.strip():
                error_message = msg.strip()
        elif isinstance(task_error, str) and task_error.strip():
            error_message = task_error.strip()
        if status is ThreeDTaskLifecycleStatus.FAILED and raw_status in {
            "CANCELED",
            "CANCELLED",
        }:
            error_message = error_message or "Task cancelled by Meshy."
        if status is ThreeDTaskLifecycleStatus.FAILED and not error_message:
            error_message = "Meshy task failed."

        result_urls: dict[str, str] = {}
        if status is ThreeDTaskLifecycleStatus.COMPLETED:
            result_urls = _extract_meshy_result_urls(data)
            progress = 100
            stage = None

        return ThreeDTaskStatusDTO(
            status=status,
            progress_percent=progress,
            result_urls=result_urls,
            stage=stage,
            error_message=error_message,
            provider_task_id=provider_task_id,
            metadata={
                "provider": "meshy",
                "raw_status": raw_status,
                "meshy_task_id": data.get("id"),
                "type": data.get("type"),
            },
        )


def _is_trip_worthy_meshy_exc(exc: BaseException) -> bool:
    if isinstance(exc, MeshyEngineError):
        if exc.status_code is None:
            return True
        return is_trip_worthy_status(exc.status_code) or exc.status_code >= 500
    match = _HTTP_STATUS_RE.search(str(exc))
    if match:
        code = int(match.group(1))
        return is_trip_worthy_status(code) or code >= 500
    return True


def _host_root(base_url: str) -> str:
    parsed = urlparse(base_url if "://" in base_url else f"https://{base_url}")
    if parsed.scheme and parsed.netloc:
        return f"{parsed.scheme}://{parsed.netloc}"
    return _DEFAULT_HOST


def _extract_meshy_task_id(data: dict[str, Any]) -> str | None:
    result = data.get("result")
    if isinstance(result, str) and result.strip():
        return result.strip()
    if isinstance(result, dict):
        nested = result.get("id") or result.get("task_id")
        if isinstance(nested, str) and nested.strip():
            return nested.strip()
    for key in ("id", "task_id"):
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _extract_meshy_result_urls(data: dict[str, Any]) -> dict[str, str]:
    urls: dict[str, str] = {}
    model_urls = data.get("model_urls")
    if isinstance(model_urls, dict):
        for key, value in model_urls.items():
            if isinstance(key, str) and isinstance(value, str) and value.strip():
                urls[key.strip().lower()] = value.strip()
    thumbnail = data.get("thumbnail_url")
    if isinstance(thumbnail, str) and thumbnail.strip():
        urls.setdefault("preview", thumbnail.strip())
    alpha = data.get("alpha_thumbnail_url")
    if isinstance(alpha, str) and alpha.strip():
        urls.setdefault("preview_alpha", alpha.strip())
    return urls


def _split_route_prefix(provider_task_id: str) -> tuple[str | None, str]:
    if ":" in provider_task_id:
        prefix, _, rest = provider_task_id.partition(":")
        if prefix in {"i2d", "t2d"} and rest.strip():
            return prefix, rest.strip()
    return None, provider_task_id


def _clamp_progress(value: object) -> int:
    try:
        progress = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0
    return max(0, min(100, progress))


def _stage_for_progress(progress: int) -> ThreeDGenerationStage:
    if progress < 33:
        return ThreeDGenerationStage.DRAFTING_MESH
    if progress < 66:
        return ThreeDGenerationStage.GENERATING_TEXTURES
    return ThreeDGenerationStage.BAKING_MAPS
