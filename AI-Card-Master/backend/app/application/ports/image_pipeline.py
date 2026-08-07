"""Ports for post-provider image pipeline steps (A1)."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.services.image_optimizer import OptimizedImage


@runtime_checkable
class ImagePipelinePort(Protocol):
    """Lossless optimisation, thumbnails, and related image transforms."""

    async def optimize_lossless(self, image_bytes: bytes) -> OptimizedImage:
        """Compress without changing visible pixels."""

    async def create_thumbnail(self, image_bytes: bytes) -> OptimizedImage:
        """Build a lightweight preview (≤100 KB target)."""
