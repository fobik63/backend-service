"""Redis-backed request rate limiting and temporary IP / API-key blocks.

Great Wall (plan §61): dual buckets — per client IP and per API key / bearer
token fingerprint — plus auto-ban helpers used by SuspiciousActivityMiddleware.

Security & Status (plan §62): global JSON blocked-threat ring + RPS second buckets.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import time
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any

from redis.exceptions import RedisError
from starlette.requests import Request

from app.domain.security_status import (
    BlockedThreatAction,
    BlockedThreatEvent,
    RequestsPerSecondMetrics,
)
from app.infrastructure.redis import get_redis_client

logger = logging.getLogger(__name__)

_BEARER_RE = re.compile(r"^Bearer\s+(.+)$", re.IGNORECASE)
_API_KEY_AUTH_RE = re.compile(
    r"^(?:Api[_-]?Key|Token)\s+(.+)$",
    re.IGNORECASE,
)

GLOBAL_THREAT_LOG_KEY = "security:threat_log:global"
RPS_BUCKET_PREFIX = "security:rps:"
_THREAT_LOG_MAX = 50


@dataclass(frozen=True, slots=True)
class RateLimitDecision:
    allowed: bool
    remaining: int
    retry_after_seconds: int = 0
    reason: str | None = None
    bucket: str | None = None


def fingerprint_api_key(raw_key: str) -> str:
    """Stable SHA-256 fingerprint so raw secrets never land in Redis keys."""

    digest = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()
    return digest[:32]


def extract_api_key_credential(request: Request) -> str | None:
    """Pull an API credential from ``X-API-Key`` or ``Authorization`` headers."""

    header_key = (request.headers.get("x-api-key") or "").strip()
    if header_key:
        return header_key

    authorization = (request.headers.get("authorization") or "").strip()
    if not authorization:
        return None

    bearer = _BEARER_RE.match(authorization)
    if bearer is not None:
        token = bearer.group(1).strip()
        return token or None

    api_key_auth = _API_KEY_AUTH_RE.match(authorization)
    if api_key_auth is not None:
        token = api_key_auth.group(1).strip()
        return token or None

    return None


async def is_ip_blocked(ip: str) -> bool:
    """Return True when the IP has an active temporary block."""

    try:
        return bool(await get_redis_client().exists(f"security:ip_block:{ip}"))
    except RedisError:
        logger.warning("Redis unavailable for IP block lookup", exc_info=True)
        return False


async def is_api_key_blocked(api_key_fingerprint: str) -> bool:
    """Return True when the API-key fingerprint has an active temporary block."""

    if not api_key_fingerprint:
        return False
    try:
        return bool(
            await get_redis_client().exists(
                f"security:apikey_block:{api_key_fingerprint}"
            )
        )
    except RedisError:
        logger.warning("Redis unavailable for API-key block lookup", exc_info=True)
        return False


async def block_ip(ip: str, *, ttl_seconds: int, reason: str) -> None:
    """Temporarily block an IP address."""

    if ttl_seconds <= 0:
        return
    try:
        await get_redis_client().set(
            f"security:ip_block:{ip}",
            reason[:200],
            ex=ttl_seconds,
        )
    except RedisError:
        logger.warning("Redis unavailable for IP block write", exc_info=True)


async def block_api_key(
    api_key_fingerprint: str,
    *,
    ttl_seconds: int,
    reason: str,
) -> None:
    """Temporarily block an API-key fingerprint."""

    if ttl_seconds <= 0 or not api_key_fingerprint:
        return
    try:
        await get_redis_client().set(
            f"security:apikey_block:{api_key_fingerprint}",
            reason[:200],
            ex=ttl_seconds,
        )
    except RedisError:
        logger.warning("Redis unavailable for API-key block write", exc_info=True)


async def claim_ban_alert_slot(subject: str, *, ttl_seconds: int) -> bool:
    """Return True once per ban window so Telegram is not spammed."""

    if ttl_seconds <= 0 or not subject:
        return False
    try:
        created = await get_redis_client().set(
            f"security:ban_alert:{subject}",
            "1",
            nx=True,
            ex=ttl_seconds,
        )
        return bool(created)
    except RedisError:
        logger.warning("Redis unavailable for ban-alert dedupe", exc_info=True)
        return True


async def record_threat_event(ip: str, *, category: str, path: str) -> int:
    """Increment threat score for an IP; return the new score."""

    key = f"security:threat_score:{ip}"
    try:
        client = get_redis_client()
        score = int(await client.incr(key))
        await client.expire(key, 3600)
        await client.lpush(
            f"security:threat_log:{ip}",
            f"{category}:{path[:120]}",
        )
        await client.ltrim(f"security:threat_log:{ip}", 0, 49)
        await client.expire(f"security:threat_log:{ip}", 86400)
        return score
    except RedisError:
        logger.warning("Redis unavailable for threat scoring", exc_info=True)
        return 0


async def append_blocked_threat(
    *,
    ip: str,
    category: str,
    path: str,
    action: BlockedThreatAction,
    http_status: int,
    score: int | None = None,
    api_key_fingerprint: str | None = None,
) -> BlockedThreatEvent:
    """Append a blocked threat JSON entry to the global ring (last 50)."""

    event = BlockedThreatEvent(
        id=str(uuid.uuid4()),
        timestamp=datetime.now(UTC),
        ip=ip,
        category=category[:128],
        path=path[:240],
        action=action,
        http_status=http_status,
        score=score,
        api_key_fingerprint=api_key_fingerprint,
    )
    payload = {
        **asdict(event),
        "timestamp": event.timestamp.isoformat(),
    }
    try:
        client = get_redis_client()
        await client.lpush(GLOBAL_THREAT_LOG_KEY, json.dumps(payload, ensure_ascii=False))
        await client.ltrim(GLOBAL_THREAT_LOG_KEY, 0, _THREAT_LOG_MAX - 1)
        await client.expire(GLOBAL_THREAT_LOG_KEY, 86400)
    except RedisError:
        logger.warning("Redis unavailable for blocked-threat log", exc_info=True)
    return event


def _parse_threat_raw(raw: str) -> BlockedThreatEvent | None:
    """Parse JSON ring entries; tolerate legacy ``ip|category|path`` strings."""

    text = (raw or "").strip()
    if not text:
        return None

    if text.startswith("{"):
        try:
            data: dict[str, Any] = json.loads(text)
        except json.JSONDecodeError:
            return None
        ts_raw = data.get("timestamp")
        try:
            timestamp = (
                datetime.fromisoformat(str(ts_raw).replace("Z", "+00:00"))
                if ts_raw
                else datetime.now(UTC)
            )
        except ValueError:
            timestamp = datetime.now(UTC)
        action_raw = str(data.get("action") or "denied")
        action: BlockedThreatAction
        if action_raw in {"denied", "banned", "rate_limited"}:
            action = action_raw  # type: ignore[assignment]
        else:
            action = "denied"
        try:
            http_status = int(data.get("http_status") or 403)
        except (TypeError, ValueError):
            http_status = 403
        score_val = data.get("score")
        score: int | None
        try:
            score = int(score_val) if score_val is not None else None
        except (TypeError, ValueError):
            score = None
        return BlockedThreatEvent(
            id=str(data.get("id") or uuid.uuid4()),
            timestamp=timestamp,
            ip=str(data.get("ip") or "unknown")[:64],
            category=str(data.get("category") or "unknown")[:128],
            path=str(data.get("path") or "/")[:240],
            action=action,
            http_status=http_status,
            score=score,
            api_key_fingerprint=(
                str(data["api_key_fingerprint"])[:32]
                if data.get("api_key_fingerprint")
                else None
            ),
        )

    # Legacy pipe format from early §62 stub.
    parts = text.split("|", 2)
    if len(parts) != 3:
        return None
    return BlockedThreatEvent(
        id=str(uuid.uuid4()),
        timestamp=datetime.now(UTC),
        ip=parts[0][:64],
        category=parts[1][:128],
        path=parts[2][:240],
        action="denied",
        http_status=403,
    )


async def list_blocked_threats(*, limit: int = 50) -> list[BlockedThreatEvent]:
    """Newest-first blocked threats for the admin Security & Status panel."""

    capped = max(1, min(int(limit), _THREAT_LOG_MAX))
    try:
        raw_items = await get_redis_client().lrange(GLOBAL_THREAT_LOG_KEY, 0, capped - 1)
    except RedisError:
        logger.warning("Redis unavailable for blocked-threat read", exc_info=True)
        return []

    events: list[BlockedThreatEvent] = []
    for raw in raw_items:
        text = raw.decode("utf-8") if isinstance(raw, bytes) else str(raw)
        parsed = _parse_threat_raw(text)
        if parsed is not None:
            events.append(parsed)
    return events


class RedisRpsMeter:
    """Fixed-second Redis counters for live RPS (plan §62)."""

    async def record_request(self) -> None:
        bucket = f"{RPS_BUCKET_PREFIX}{int(time.time())}"
        try:
            client = get_redis_client()
            await client.incr(bucket)
            await client.expire(bucket, 10)
        except RedisError:
            logger.debug("Redis unavailable for RPS increment", exc_info=True)

    async def current_rps(self, *, window_seconds: int) -> RequestsPerSecondMetrics:
        window = max(1, min(int(window_seconds), 60))
        now = int(time.time())
        keys = [f"{RPS_BUCKET_PREFIX}{now - offset}" for offset in range(window)]
        try:
            client = get_redis_client()
            values = await client.mget(keys)
        except RedisError:
            logger.warning("Redis unavailable for RPS read", exc_info=True)
            return RequestsPerSecondMetrics(
                rps=0.0,
                window_seconds=window,
                requests_in_window=0,
            )

        total = 0
        for value in values:
            if value is None:
                continue
            try:
                total += int(value)
            except (TypeError, ValueError):
                continue
        return RequestsPerSecondMetrics(
            rps=round(total / float(window), 2),
            window_seconds=window,
            requests_in_window=total,
        )


async def record_request_for_rps() -> None:
    """Module-level helper used by middleware."""

    await RedisRpsMeter().record_request()


async def check_rate_limit_bucket(
    *,
    bucket: str,
    limit: int,
    window_seconds: int,
) -> RateLimitDecision:
    """Sliding fixed-window counter for an arbitrary Redis bucket. Fail-open."""

    if limit <= 0 or window_seconds <= 0 or not bucket:
        return RateLimitDecision(allowed=True, remaining=0, bucket=bucket or None)

    key = f"security:rate:{bucket}:{window_seconds}"
    try:
        client = get_redis_client()
        count = int(await client.incr(key))
        if count == 1:
            await client.expire(key, window_seconds)
        ttl = int(await client.ttl(key))
        remaining = max(limit - count, 0)
        if count > limit:
            return RateLimitDecision(
                allowed=False,
                remaining=0,
                retry_after_seconds=max(ttl, 1),
                reason="rate_limit",
                bucket=bucket,
            )
        return RateLimitDecision(allowed=True, remaining=remaining, bucket=bucket)
    except RedisError:
        logger.warning("Redis unavailable for rate limiting; allowing request")
        return RateLimitDecision(allowed=True, remaining=limit, bucket=bucket)


async def check_rate_limit(
    *,
    ip: str,
    limit: int,
    window_seconds: int,
) -> RateLimitDecision:
    """Fixed-window counter per IP (backward-compatible wrapper)."""

    return await check_rate_limit_bucket(
        bucket=f"ip:{ip}",
        limit=limit,
        window_seconds=window_seconds,
    )


async def check_api_key_rate_limit(
    *,
    api_key_fingerprint: str,
    limit: int,
    window_seconds: int,
) -> RateLimitDecision:
    """Fixed-window counter per API-key / bearer fingerprint."""

    return await check_rate_limit_bucket(
        bucket=f"apikey:{api_key_fingerprint}",
        limit=limit,
        window_seconds=window_seconds,
    )
