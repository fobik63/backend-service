"""Shared timeout/retry primitives for outbound HTTP integrations.

Keeps Midjourney / Claude / YooKassa / marketplace clients from crashing the
API process when an upstream stalls or flaps.

Also exposes bounded concurrency helpers so highload workflows can fan out
external I/O in 1–2 gathers without losing per-call isolation.
"""

from __future__ import annotations

import asyncio
import logging
import random
from collections.abc import Awaitable, Callable, Sequence
from typing import TypeVar

import httpx

logger = logging.getLogger(__name__)

TRANSIENT_HTTP_CODES: frozenset[int] = frozenset({408, 425, 429, 500, 502, 503, 504})
TRANSPORT_ERRORS: tuple[type[BaseException], ...] = (
    httpx.TimeoutException,
    httpx.NetworkError,
    httpx.RemoteProtocolError,
)

T = TypeVar("T")
R = TypeVar("R")


def compute_retry_delay(
    attempt: int,
    *,
    base_delay_seconds: float,
    response: httpx.Response | None = None,
    max_delay_seconds: float = 15.0,
) -> float:
    """Exponential backoff with optional Retry-After and jitter."""

    if response is not None:
        retry_after = response.headers.get("Retry-After")
        if retry_after:
            try:
                parsed = float(retry_after)
                if parsed > 0:
                    return min(parsed, max_delay_seconds)
            except ValueError:
                logger.debug("Ignoring non-numeric Retry-After: %s", retry_after)
    return min(
        base_delay_seconds * (2 ** (attempt - 1)) + random.uniform(0.0, 0.35),
        max_delay_seconds,
    )


async def call_with_transport_retry(
    operation: Callable[[], Awaitable[T]],
    *,
    max_retries: int,
    base_delay_seconds: float,
    operation_name: str,
    is_transient_result: Callable[[T], bool] | None = None,
) -> T:
    """Retry an async call on transport errors (and optional soft failures).

    Raises the last transport exception when retries are exhausted. Callers that
    need a domain error should wrap this helper.
    """

    attempts = max(max_retries, 0) + 1
    last_error: BaseException | None = None
    for attempt in range(1, attempts + 1):
        try:
            result = await operation()
            if is_transient_result is not None and is_transient_result(result):
                if attempt >= attempts:
                    return result
                delay = compute_retry_delay(
                    attempt,
                    base_delay_seconds=base_delay_seconds,
                    response=result if isinstance(result, httpx.Response) else None,
                )
                logger.warning(
                    "%s soft-failed (attempt %s/%s); retrying in %.2fs",
                    operation_name,
                    attempt,
                    attempts,
                    delay,
                )
                await asyncio.sleep(delay)
                continue
            return result
        except TRANSPORT_ERRORS as exc:
            last_error = exc
            if attempt >= attempts:
                break
            delay = compute_retry_delay(
                attempt,
                base_delay_seconds=base_delay_seconds,
            )
            logger.warning(
                "%s transport error (attempt %s/%s): %s; retrying in %.2fs",
                operation_name,
                attempt,
                attempts,
                exc,
                delay,
            )
            await asyncio.sleep(delay)
    assert last_error is not None
    raise last_error


async def gather_bounded(
    items: Sequence[T],
    worker: Callable[[T], Awaitable[R]],
    *,
    limit: int,
    return_exceptions: bool = False,
) -> list[R | BaseException]:
    """Run ``worker`` over ``items`` with a concurrency cap.

    Preserves input order. When ``return_exceptions`` is True, failures become
    result values (caller isolates stability per item). Otherwise the first
    exception propagates after in-flight tasks settle via ``asyncio.gather``.
    """

    if not items:
        return []
    concurrency = max(1, limit)
    semaphore = asyncio.Semaphore(concurrency)

    async def _run(item: T) -> R:
        async with semaphore:
            return await worker(item)

    return list(
        await asyncio.gather(
            *(_run(item) for item in items),
            return_exceptions=return_exceptions,
        )
    )


async def gather_independent(
    *operations: Callable[[], Awaitable[T]],
) -> list[T | BaseException]:
    """Fan out independent awaitables; never let one failure cancel siblings."""

    if not operations:
        return []
    return list(
        await asyncio.gather(
            *(operation() for operation in operations),
            return_exceptions=True,
        )
    )
