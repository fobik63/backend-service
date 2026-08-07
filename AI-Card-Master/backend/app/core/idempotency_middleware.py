"""Redis idempotency middleware for coin charges and generation task creation.

When ``X-Idempotency-Key`` (or legacy ``Idempotency-Key``) is present on a
protected POST/PUT:

- First sight → claim ``PROCESSING`` in Redis (TTL 60s by default).
- Concurrent replay while processing → HTTP 409 Conflict.
- After a successful (2xx) response → cache status + body (TTL 15 min).
- Later replay → return the cached response without re-running handlers.
"""

from __future__ import annotations

import hashlib
import logging
import re
from collections.abc import Awaitable, Callable

from fastapi import Request, status
from fastapi.responses import JSONResponse, Response
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.config import Settings, get_settings
from app.infrastructure.idempotency_store import (
    STATUS_COMPLETED,
    STATUS_PROCESSING,
    claim_processing,
    get_idempotency_record,
    release_processing,
    store_completed_response,
)
from app.infrastructure.redis import RedisUnavailableError

logger = logging.getLogger(__name__)

_MUTATING_METHODS = frozenset({"POST", "PUT"})

# Coin-charging / generation-task surfaces (method filter already applied).
_PROTECTED_PATH_PREFIXES: tuple[str, ...] = (
    "/api/v1/generations",
    "/api/v1/bulk-generations",
    "/api/v1/smart-variants",
    "/api/v1/brand-loras",
    "/api/v1/claude-analyses",
    "/api/v1/claude/reasoning",
    "/api/v1/claude/visual-audit",
    "/api/v1/pain-analysis",
    "/api/v1/oracle",
    "/api/v1/ai-strategy",
    "/api/v1/ab-tests",
    "/api/v1/analytics",
    "/api/v1/payments/create",
    "/api/v1/3d",
)

_EXACT_PROTECTED_PATHS: frozenset[str] = frozenset(
    {
        "/api/v1/payments/create",
    }
)

_KEY_PATTERN = re.compile(r"^[A-Za-z0-9._:-]+$")
_MIN_KEY_LEN = 8
_MAX_KEY_LEN = 255
_MAX_CACHED_BODY_BYTES = 256 * 1024


class IdempotencyMiddleware(BaseHTTPMiddleware):
    """Prevent duplicate coin deductions and generation creates via Redis."""

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        settings = get_settings()
        if not settings.idempotency_middleware_enabled:
            return await call_next(request)

        if request.method not in _MUTATING_METHODS:
            return await call_next(request)

        if not _is_protected_path(request.url.path):
            return await call_next(request)

        raw_key = _extract_idempotency_key(request)
        if raw_key is None:
            return await call_next(request)

        key = raw_key.strip()
        if not _is_valid_key(key):
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content={
                    "success": False,
                    "code": "INVALID_IDEMPOTENCY_KEY",
                    "detail": (
                        "X-Idempotency-Key must be 8–255 chars of "
                        "[A-Za-z0-9._:-]."
                    ),
                },
            )

        scope = _build_scope(request)
        try:
            owned = await _try_claim_or_replay(
                scope=scope,
                key=key,
                settings=settings,
            )
        except _IdempotencyReplay as replay:
            return replay.response
        except RedisUnavailableError:
            logger.warning(
                "Idempotency Redis unavailable; failing open",
                exc_info=True,
            )
            return await call_next(request)

        if not owned:
            return _conflict_in_progress()

        try:
            response = await call_next(request)
        except Exception:
            await _safe_release(scope=scope, key=key)
            raise

        return await _finalize_owner_response(
            response=response,
            scope=scope,
            key=key,
            settings=settings,
        )


class _IdempotencyReplay(Exception):
    """Carry a cached response out of claim/replay without nesting returns."""

    def __init__(self, response: Response) -> None:
        self.response = response
        super().__init__("idempotency replay")


async def _try_claim_or_replay(
    *, scope: str, key: str, settings: Settings
) -> bool:
    """Return True when this request owns PROCESSING; raise on completed replay.

    Returns False when another request still holds PROCESSING.
    """

    claimed = await claim_processing(
        scope=scope,
        idempotency_key=key,
        ttl_seconds=settings.idempotency_processing_ttl_seconds,
    )
    if claimed:
        return True

    record = await get_idempotency_record(scope=scope, idempotency_key=key)
    if record is None:
        # Marker expired between lost NX and GET — claim once more.
        claimed = await claim_processing(
            scope=scope,
            idempotency_key=key,
            ttl_seconds=settings.idempotency_processing_ttl_seconds,
        )
        return bool(claimed)

    status_name = record.get("status")
    if status_name == STATUS_COMPLETED:
        raise _IdempotencyReplay(_replay_completed(record))
    if status_name == STATUS_PROCESSING:
        return False
    return False


def _conflict_in_progress() -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_409_CONFLICT,
        content={
            "success": False,
            "code": "IDEMPOTENCY_IN_PROGRESS",
            "detail": "Запрос уже обрабатывается",
        },
    )


def _is_protected_path(path: str) -> bool:
    normalized = path.rstrip("/") or "/"
    if normalized in {p.rstrip("/") for p in _EXACT_PROTECTED_PATHS}:
        return True
    for prefix in _PROTECTED_PATH_PREFIXES:
        if prefix in _EXACT_PROTECTED_PATHS:
            continue
        base = prefix.rstrip("/")
        if normalized == base or normalized.startswith(base + "/"):
            return True
    return False


def _extract_idempotency_key(request: Request) -> str | None:
    """Prefer ``X-Idempotency-Key``; fall back to ``Idempotency-Key``."""

    for header in ("x-idempotency-key", "idempotency-key"):
        value = request.headers.get(header)
        if value is not None and value.strip():
            return value
    return None


def _is_valid_key(key: str) -> bool:
    if not (_MIN_KEY_LEN <= len(key) <= _MAX_KEY_LEN):
        return False
    return bool(_KEY_PATTERN.fullmatch(key))


def _build_scope(request: Request) -> str:
    """Scope keys by route + caller fingerprint to avoid cross-user collisions."""

    path = (request.url.path.rstrip("/") or "/").lower()
    auth = request.headers.get("authorization") or request.headers.get("x-api-key") or ""
    fingerprint = hashlib.sha256(
        f"{request.method}:{path}:{auth}".encode()
    ).hexdigest()[:32]
    return fingerprint


def _replay_completed(record: dict[str, object]) -> Response:
    status_code = int(record.get("status_code") or status.HTTP_200_OK)
    body = record.get("body")
    media_type = record.get("media_type")
    content = body if isinstance(body, str) else ""
    mt = media_type if isinstance(media_type, str) else "application/json"
    return Response(
        content=content,
        status_code=status_code,
        media_type=mt,
        headers={"X-Idempotency-Replayed": "true"},
    )


async def _finalize_owner_response(
    *,
    response: Response,
    scope: str,
    key: str,
    settings: Settings,
) -> Response:
    body = await _buffer_response_body(response)
    headers = {
        header_name: value
        for header_name, value in response.headers.items()
        if header_name.lower() != "content-length"
    }

    if 200 <= response.status_code < 300:
        if len(body) <= _MAX_CACHED_BODY_BYTES:
            try:
                text = body.decode(response.charset or "utf-8")
                await store_completed_response(
                    scope=scope,
                    idempotency_key=key,
                    status_code=response.status_code,
                    body=text,
                    media_type=response.media_type,
                    ttl_seconds=settings.idempotency_response_ttl_seconds,
                )
            except (RedisUnavailableError, UnicodeDecodeError):
                logger.warning(
                    "Could not cache idempotent response; releasing PROCESSING",
                    exc_info=True,
                )
                await _safe_release(scope=scope, key=key)
        else:
            logger.warning(
                "Idempotent response body too large (%s bytes); not caching",
                len(body),
            )
            await _safe_release(scope=scope, key=key)
    else:
        await _safe_release(scope=scope, key=key)

    return Response(
        content=body,
        status_code=response.status_code,
        headers=headers,
        media_type=response.media_type,
        background=response.background,
    )


async def _buffer_response_body(response: Response) -> bytes:
    body_attr = getattr(response, "body", None)
    if isinstance(body_attr, (bytes, bytearray, memoryview)):
        return bytes(body_attr)

    chunks: list[bytes] = []
    body_iterator = getattr(response, "body_iterator", None)
    if body_iterator is None:
        return b""
    async for chunk in body_iterator:
        if isinstance(chunk, bytes):
            chunks.append(chunk)
        elif isinstance(chunk, memoryview):
            chunks.append(chunk.tobytes())
        elif isinstance(chunk, str):
            chunks.append(chunk.encode("utf-8"))
        else:
            chunks.append(bytes(chunk))
    return b"".join(chunks)


async def _safe_release(*, scope: str, key: str) -> None:
    try:
        await release_processing(scope=scope, idempotency_key=key)
    except RedisUnavailableError:
        logger.warning(
            "Could not release idempotency PROCESSING marker",
            exc_info=True,
        )
