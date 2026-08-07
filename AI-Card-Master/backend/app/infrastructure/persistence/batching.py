"""Shared batching helpers for persistence-layer bulk writes."""

from __future__ import annotations

from collections.abc import Sequence
from typing import TypeVar

T = TypeVar("T")

# Mass INSERT…ON CONFLICT / bulk insert window (plan: 100–500 rows per statement).
DEFAULT_UPSERT_BATCH_SIZE = 500
MIN_UPSERT_BATCH_SIZE = 100
MAX_UPSERT_BATCH_SIZE = 500


def clamp_upsert_batch_size(size: int) -> int:
    """Keep batch size inside the agreed 100–500 window."""

    return max(MIN_UPSERT_BATCH_SIZE, min(int(size), MAX_UPSERT_BATCH_SIZE))


def chunk_rows(items: Sequence[T], size: int = DEFAULT_UPSERT_BATCH_SIZE) -> list[list[T]]:
    """Split ``items`` into contiguous chunks of at most ``size`` (clamped)."""

    chunk_size = clamp_upsert_batch_size(size)
    return [list(items[index : index + chunk_size]) for index in range(0, len(items), chunk_size)]
