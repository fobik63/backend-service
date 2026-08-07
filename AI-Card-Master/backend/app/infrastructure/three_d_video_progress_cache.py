"""Redis-backed live progress cache for 360° video render jobs."""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID

from app.domain.three_d_video import (
    REDIS_THREE_D_VIDEO_PROGRESS_TTL_SECONDS,
    ThreeDVideoProgressSnapshot,
    redis_three_d_video_progress_channel,
    redis_three_d_video_progress_key,
)
from app.infrastructure.redis import (
    RedisUnavailableError,
    cache_json,
    get_cached_json,
    get_redis_client,
)

logger = logging.getLogger(__name__)


class RedisThreeDVideoProgressCache:
    """Fail-open progress mirror; Redis outages never fail the render worker."""

    def __init__(
        self, *, ttl_seconds: int = REDIS_THREE_D_VIDEO_PROGRESS_TTL_SECONDS
    ) -> None:
        self._ttl_seconds = max(60, int(ttl_seconds))

    async def publish(self, snapshot: ThreeDVideoProgressSnapshot) -> None:
        payload = snapshot.to_dict()
        key = redis_three_d_video_progress_key(snapshot.video_task_id)
        channel = redis_three_d_video_progress_channel(snapshot.video_task_id)
        try:
            await cache_json(key, payload, self._ttl_seconds)
        except RedisUnavailableError:
            logger.warning(
                "Redis unavailable; skipped 3D video progress cache key=%s", key
            )
            return
        try:
            client = get_redis_client()
            await client.publish(channel, json.dumps(payload, ensure_ascii=False))
        except Exception:
            logger.warning(
                "Redis pub/sub publish failed for 3D video task=%s",
                snapshot.video_task_id,
                exc_info=True,
            )

    async def get(self, video_task_id: UUID) -> ThreeDVideoProgressSnapshot | None:
        try:
            raw = await get_cached_json(redis_three_d_video_progress_key(video_task_id))
        except RedisUnavailableError:
            logger.warning(
                "Redis unavailable; 3D video progress cache miss task=%s",
                video_task_id,
            )
            return None
        if not raw:
            return None
        try:
            return ThreeDVideoProgressSnapshot.from_dict(raw)
        except (KeyError, TypeError, ValueError):
            logger.warning(
                "Invalid 3D video progress payload for task=%s", video_task_id
            )
            return None

    async def subscribe_payloads(
        self, video_task_id: UUID
    ) -> AsyncIterator[dict[str, Any]]:
        """Yield decoded pub/sub payloads until the caller stops iterating."""

        channel = redis_three_d_video_progress_channel(video_task_id)
        client = get_redis_client()
        pubsub = client.pubsub()
        try:
            await pubsub.subscribe(channel)
            async for message in pubsub.listen():
                if message is None:
                    continue
                if message.get("type") != "message":
                    continue
                data = message.get("data")
                if isinstance(data, bytes):
                    data = data.decode("utf-8", errors="replace")
                if not isinstance(data, str) or not data.strip():
                    continue
                try:
                    payload = json.loads(data)
                except json.JSONDecodeError:
                    continue
                if isinstance(payload, dict):
                    yield payload
        finally:
            try:
                await pubsub.unsubscribe(channel)
                await pubsub.aclose()
            except Exception:
                logger.debug("3D video progress pubsub cleanup failed", exc_info=True)
