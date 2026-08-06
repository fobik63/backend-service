"""Inspect generated slide images from S3 for marketplace validation."""

from __future__ import annotations

import io
import logging

from PIL import Image

from app.core.config import get_settings
from app.domain.export import ImageAssetMeta
from app.services.s3_storage import S3StorageError, get_s3_storage

logger = logging.getLogger(__name__)


class S3ImageAssetAdapter:
    """ImageAssetPort backed by Selectel/S3 storage."""

    async def inspect_images(
        self, object_keys: tuple[str, ...]
    ) -> tuple[ImageAssetMeta, ...]:
        storage = get_s3_storage()
        max_bytes = get_settings().generation_max_result_bytes
        inspected: list[ImageAssetMeta] = []
        for key in object_keys:
            try:
                payload = await storage.download_bytes(
                    object_key=key, max_bytes=max_bytes
                )
            except S3StorageError as exc:
                raise RuntimeError(f"Failed to download image '{key}': {exc}") from exc
            with Image.open(io.BytesIO(payload)) as image:
                width, height = image.size
                fmt = (image.format or "JPEG").upper()
            inspected.append(
                ImageAssetMeta(
                    object_key=key,
                    width=width,
                    height=height,
                    size_bytes=len(payload),
                    format=fmt,
                )
            )
        return tuple(inspected)

    async def public_urls(self, object_keys: tuple[str, ...]) -> tuple[str, ...]:
        storage = get_s3_storage()
        urls: list[str] = []
        for key in object_keys:
            try:
                url = await storage.generate_presigned_url(object_key=key)
            except S3StorageError as exc:
                raise RuntimeError(f"Failed to presign image '{key}': {exc}") from exc
            urls.append(url)
        return tuple(urls)
