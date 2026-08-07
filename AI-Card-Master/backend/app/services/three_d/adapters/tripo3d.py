"""Tripo3D OpenAPI adapter (text-to-model / image-to-model)."""

from __future__ import annotations

import logging
import re
from typing import Any

import httpx

from app.application.ports.circuit_breaker import CircuitBreakerPort
from app.domain.circuit_breaker import CIRCUIT_TRIPO3D, is_trip_worthy_status
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

_TRIPO_STATUS_MAP: dict[str, ThreeDTaskLifecycleStatus] = {
    "queued": ThreeDTaskLifecycleStatus.QUEUED,
    "running": ThreeDTaskLifecycleStatus.PROCESSING,
    "success": ThreeDTaskLifecycleStatus.COMPLETED,
    "failed": ThreeDTaskLifecycleStatus.FAILED,
    "cancelled": ThreeDTaskLifecycleStatus.FAILED,
    "canceled": ThreeDTaskLifecycleStatus.FAILED,
    "banned": ThreeDTaskLifecycleStatus.FAILED,
    "expired": ThreeDTaskLifecycleStatus.FAILED,
    "unknown": ThreeDTaskLifecycleStatus.FAILED,
}

_DEFAULT_MODEL = "v2.5-20250123"
_HTTP_STATUS_RE = re.compile(r"HTTP (\d{3})")


class Tripo3DEngineError(RuntimeError):
    """Raised when Tripo3D HTTP API returns an unexpected error."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class Tripo3DEngineAdapter(BaseThreeDEngine):
    """``BaseThreeDEngine`` backed by Tripo3D ``/v2/openapi/task``.

    Outbound HTTP is guarded by the shared Redis CircuitBreaker: after
    ``failure_threshold`` trip-worthy responses (429/5xx/timeouts) the circuit
    opens and callers receive ``ThreeDServiceUnavailableError``.
    """

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = "https://api.tripo3d.ai/v2/openapi",
        timeout_seconds: float = 60.0,
        default_model: str = _DEFAULT_MODEL,
        client: httpx.AsyncClient | None = None,
        circuit_breaker: CircuitBreakerPort | None = None,
    ) -> None:
        key = api_key.strip()
        if not key:
            raise ValueError("Tripo3DEngineAdapter requires a non-empty api_key.")
        root = base_url.strip().rstrip("/")
        if not root:
            raise ValueError("Tripo3DEngineAdapter requires a non-empty base_url.")

        self._api_key = key
        self._base_url = root
        self._default_model = default_model.strip() or _DEFAULT_MODEL
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
        self._circuit_name = CIRCUIT_TRIPO3D
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

        payload = self._build_create_payload(cleaned_prompt, cleaned_image, params)
        data = await self._request_json("POST", f"{self._base_url}/task", json=payload)
        task_id = _extract_tripo_task_id(data)
        if not task_id:
            raise Tripo3DEngineError(f"Tripo3D create response missing task_id: {data!r}")
        return task_id

    async def get_task_status(self, provider_task_id: str) -> ThreeDTaskStatusDTO:
        task_id = provider_task_id.strip()
        if not task_id:
            raise ValueError("provider_task_id must be a non-empty string.")

        data = await self._request_json("GET", f"{self._base_url}/task/{task_id}")
        body = _unwrap_tripo_data(data)
        return self._to_dto(body, provider_task_id=task_id)

    async def cancel_task(self, provider_task_id: str) -> bool:
        """Tripo OpenAPI has no public cancel endpoint; best-effort DELETE/POST.

        Returns ``True`` only when the provider acknowledges cancellation.
        """

        task_id = provider_task_id.strip()
        if not task_id:
            return False

        attempts = (
            ("POST", f"{self._base_url}/task/{task_id}/cancel"),
            ("DELETE", f"{self._base_url}/task/{task_id}"),
        )
        for method, url in attempts:
            try:
                response = await self._client.request(method, url)
            except httpx.HTTPError as exc:
                logger.warning("Tripo3D cancel %s %s failed: %s", method, url, exc)
                continue
            if response.status_code in {200, 202, 204}:
                return True
            if response.status_code in {404, 405, 409, 422}:
                continue
            logger.warning(
                "Tripo3D cancel %s %s returned HTTP %s: %s",
                method,
                url,
                response.status_code,
                response.text[:300],
            )
        logger.info(
            "Tripo3D cancel unsupported for task_id=%s; returning False.",
            task_id,
        )
        return False

    def _build_create_payload(
        self,
        prompt: str,
        image_url: str | None,
        params: dict[str, Any],
    ) -> dict[str, Any]:
        if image_url is not None:
            payload: dict[str, Any] = {
                "type": "image_to_model",
                "file": {
                    "type": "url",
                    "url": image_url,
                },
            }
            if prompt:
                payload["prompt"] = prompt[:1024]
        else:
            payload = {
                "type": "text_to_model",
                "prompt": prompt[:1024],
            }

        model = params.get("model") or params.get("model_version") or self._default_model
        if model:
            # v2 accepts model_version; newer clients also send model.
            payload["model_version"] = str(model)
            payload["model"] = str(model)

        optional_keys = (
            "negative_prompt",
            "model_seed",
            "image_seed",
            "face_limit",
            "texture",
            "pbr",
            "texture_seed",
            "texture_quality",
            "geometry_quality",
            "auto_size",
            "quad",
            "smart_low_poly",
            "generate_parts",
            "compress",
            "export_uv",
        )
        for key in optional_keys:
            if key in params:
                payload[key] = params[key]
        if "polycount_target" in params and "face_limit" not in payload:
            payload["face_limit"] = params["polycount_target"]
        if "polycount_limit" in params and "face_limit" not in payload:
            payload["face_limit"] = params["polycount_limit"]
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
                is_trip_worthy_exc=_is_trip_worthy_tripo_exc,
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
            raise Tripo3DEngineError(
                f"Tripo3D request timed out: {method} {url}",
                status_code=None,
            ) from exc
        except httpx.HTTPError as exc:
            raise Tripo3DEngineError(
                f"Tripo3D transport error: {exc}",
                status_code=None,
            ) from exc

        if response.status_code >= 400:
            raise Tripo3DEngineError(
                f"Tripo3D HTTP {response.status_code} for {method} {url}: "
                f"{response.text[:500]}",
                status_code=response.status_code,
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise Tripo3DEngineError("Tripo3D returned non-JSON body.") from exc
        if not isinstance(payload, dict):
            raise Tripo3DEngineError(
                f"Tripo3D JSON root must be an object, got {type(payload)!r}"
            )

        code = payload.get("code")
        if code is not None and code != 0:
            raise Tripo3DEngineError(
                f"Tripo3D API code={code}: {payload.get('message') or payload!r}",
                status_code=None,
            )
        return payload

    @classmethod
    def _to_dto(cls, data: dict[str, Any], *, provider_task_id: str) -> ThreeDTaskStatusDTO:
        raw_status = str(data.get("status") or "queued").strip().lower()
        status = _TRIPO_STATUS_MAP.get(raw_status, ThreeDTaskLifecycleStatus.PROCESSING)
        progress = _clamp_progress(data.get("progress", 0))
        stage = (
            _stage_for_progress(progress)
            if status is ThreeDTaskLifecycleStatus.PROCESSING
            else None
        )

        error_message: str | None = None
        for key in ("error_message", "message", "error"):
            value = data.get(key)
            if isinstance(value, str) and value.strip():
                error_message = value.strip()
                break
        if status is ThreeDTaskLifecycleStatus.FAILED and raw_status in {
            "cancelled",
            "canceled",
        }:
            error_message = error_message or "Task cancelled by Tripo3D."
        if status is ThreeDTaskLifecycleStatus.FAILED and not error_message:
            error_code = data.get("error_code")
            error_message = (
                f"Tripo3D task failed (error_code={error_code})."
                if error_code is not None
                else "Tripo3D task failed."
            )

        result_urls: dict[str, str] = {}
        if status is ThreeDTaskLifecycleStatus.COMPLETED:
            result_urls = _extract_tripo_result_urls(data.get("output"))
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
                "provider": "tripo3d",
                "raw_status": raw_status,
                "type": data.get("type"),
                "credits_consumed": data.get("credits_consumed"),
            },
        )


def _is_trip_worthy_tripo_exc(exc: BaseException) -> bool:
    if isinstance(exc, Tripo3DEngineError):
        if exc.status_code is None:
            # Timeouts / transport / vendor business codes — treat as trip-worthy
            # only for timeouts/transport (message markers); API code!=0 is not.
            text = str(exc).lower()
            if "timed out" in text or "transport error" in text:
                return True
            if "api code=" in text:
                return False
            return True
        return is_trip_worthy_status(exc.status_code) or exc.status_code >= 500
    match = _HTTP_STATUS_RE.search(str(exc))
    if match:
        code = int(match.group(1))
        return is_trip_worthy_status(code) or code >= 500
    return True


def _unwrap_tripo_data(payload: dict[str, Any]) -> dict[str, Any]:
    data = payload.get("data")
    if isinstance(data, dict):
        return data
    return payload


def _extract_tripo_task_id(payload: dict[str, Any]) -> str | None:
    data = _unwrap_tripo_data(payload)
    for key in ("task_id", "id"):
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    value = payload.get("task_id")
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _extract_tripo_result_urls(output: object) -> dict[str, str]:
    if not isinstance(output, dict):
        return {}
    urls: dict[str, str] = {}
    model_url = output.get("model_url") or output.get("pbr_model_url")
    if isinstance(model_url, str) and model_url.strip():
        urls["glb"] = model_url.strip()
    for key in ("base_model_url", "model", "glb", "obj", "fbx", "usdz"):
        value = output.get(key)
        if isinstance(value, str) and value.strip():
            urls.setdefault(key if key != "model" else "glb", value.strip())
    preview = output.get("rendered_image_url") or output.get("preview")
    if isinstance(preview, str) and preview.strip():
        urls["preview"] = preview.strip()
    return urls


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
