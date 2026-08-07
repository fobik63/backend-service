"""Redis adapter for competitor card snapshots (Semantic Filtering Delta)."""

from __future__ import annotations

import logging

from app.domain.semantic_filter import (
    CompetitorCardSnapshot,
    redis_competitor_snapshot_key,
    snapshot_from_dict,
    snapshot_to_dict,
)
from app.infrastructure.claude_stage_cache import RedisClaudeStageCache

logger = logging.getLogger(__name__)


class RedisCompetitorSnapshotStore:
    """Fail-open prior-card store used by Semantic Filtering."""

    def __init__(self, cache: RedisClaudeStageCache | None = None) -> None:
        self._cache = cache or RedisClaudeStageCache()

    async def get_snapshot(
        self, *, marketplace: str, article: str
    ) -> CompetitorCardSnapshot | None:
        key = redis_competitor_snapshot_key(marketplace=marketplace, article=article)
        payload = await self._cache.get(key)
        return snapshot_from_dict(payload)

    async def put_snapshot(
        self,
        snapshot: CompetitorCardSnapshot,
        *,
        ttl_seconds: int,
    ) -> None:
        if ttl_seconds <= 0:
            return
        key = redis_competitor_snapshot_key(
            marketplace=snapshot.marketplace,
            article=snapshot.article,
        )
        await self._cache.set(key, snapshot_to_dict(snapshot), ttl_seconds)
