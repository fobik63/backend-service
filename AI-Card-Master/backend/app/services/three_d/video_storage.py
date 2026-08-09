"""S3/MinIO uploader for 360° video assets (MP4 / WebP / GIF) with Cache-Control."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Protocol
from uuid import UUID

from app.domain.three_d_video import (
    VIDEO_ASSET_CACHE_CONTROL,
    VIDEO_CONTENT_TYPES,
    VIDEO_FILE_EXTENSIONS,
    VideoAssetFormat,
    VideoPresignedUrls,
    VideoUploadResult,
)
from app.services.s3_storage import S3UploadResult, SelectelS3Storage, get_s3_storage

logger = logging.getLogger(__name__)

_KEY_PREFIX = "three-d-video"

__all__ = [
    "VideoAssetUploader",
    "VideoPresignedUrls",
    "VideoUploadResult",
    "get_video_asset_uploader",
]


class _VideoS3Client(Protocol):
    """Minimal S3 surface used by VideoAssetUploader (testable)."""

    async def upload_bytes(
        self,
        *,
        object_key: str,
        data: bytes,
        content_type: str,
        presign: bool = True,
        cache_control: str | None = None,
    ) -> S3UploadResult: ...

    async def upload_file(
        self,
        *,
        object_key: str,
        file_path: str | Path,
        content_type: str,
        presign: bool = True,
        cache_control: str | None = None,
    ) -> S3UploadResult: ...

    async def generate_presigned_url(
        self,
        *,
        object_key: str,
        expires_in: int | None = None,
    ) -> str: ...

    async def delete_object(self, *, object_key: str) -> None: ...


class VideoAssetUploader:
    """Async uploader for orbital video binaries with long-lived Cache-Control.

    Objects live under ``three-d-video/{user_id}/{video_task_id}/…`` with:
    - MP4  → ``video/mp4``
    - WebP → ``image/webp``
    - GIF  → ``image/gif``
    - ``Cache-Control: public, max-age=31536000, immutable``
    """

    def __init__(self, client: _VideoS3Client | None = None) -> None:
        self._client: _VideoS3Client = client or get_s3_storage()

    @staticmethod
    def content_type_for(asset_format: VideoAssetFormat) -> str:
        return VIDEO_CONTENT_TYPES[asset_format]

    @staticmethod
    def build_object_key(
        *,
        user_id: UUID,
        video_task_id: UUID,
        asset_format: VideoAssetFormat,
        filename: str | None = None,
    ) -> str:
        """Build a deterministic, namespaced object key for a video asset."""

        ext = VIDEO_FILE_EXTENSIONS[asset_format]
        if filename is not None and filename.strip():
            stem = Path(filename.strip()).stem or asset_format.value
            safe_stem = "".join(
                ch if ch.isalnum() or ch in {"-", "_"} else "-" for ch in stem
            ).strip("-") or asset_format.value
            return f"{_KEY_PREFIX}/{user_id}/{video_task_id}/{safe_stem}.{ext}"
        return f"{_KEY_PREFIX}/{user_id}/{video_task_id}/{asset_format.value}.{ext}"

    async def upload_bytes(
        self,
        *,
        user_id: UUID,
        video_task_id: UUID,
        asset_format: VideoAssetFormat,
        data: bytes,
        filename: str | None = None,
        presign: bool = True,
        cache_control: str = VIDEO_ASSET_CACHE_CONTROL,
    ) -> VideoUploadResult:
        """Upload an in-memory video/preview binary with correct MIME + cache."""

        if not data:
            raise ValueError("Cannot upload empty video payload.")
        content_type = self.content_type_for(asset_format)
        object_key = self.build_object_key(
            user_id=user_id,
            video_task_id=video_task_id,
            asset_format=asset_format,
            filename=filename,
        )
        uploaded = await self._client.upload_bytes(
            object_key=object_key,
            data=data,
            content_type=content_type,
            presign=presign,
            cache_control=cache_control,
        )
        logger.info(
            "Uploaded video %s (%s bytes, %s, cache=%s) → %s",
            asset_format.value,
            len(data),
            content_type,
            cache_control,
            object_key,
        )
        return VideoUploadResult(
            format=asset_format,
            object_key=uploaded.object_key,
            content_type=content_type,
            size_bytes=len(data),
            presigned_url=uploaded.presigned_url,
            etag=uploaded.etag,
        )

    async def upload_file(
        self,
        *,
        user_id: UUID,
        video_task_id: UUID,
        asset_format: VideoAssetFormat,
        file_path: str | Path,
        filename: str | None = None,
        presign: bool = True,
        cache_control: str = VIDEO_ASSET_CACHE_CONTROL,
    ) -> VideoUploadResult:
        """Multipart-upload a large local video file without loading it into RAM."""

        path = Path(file_path)

        def _inspect_path() -> tuple[bool, int]:
            if not path.is_file():
                return False, 0
            return True, path.stat().st_size

        is_file, size = await asyncio.to_thread(_inspect_path)
        if not is_file:
            raise ValueError(f"Upload path is not a file: {path}")
        if size <= 0:
            raise ValueError("Cannot upload empty video file.")
        content_type = self.content_type_for(asset_format)
        object_key = self.build_object_key(
            user_id=user_id,
            video_task_id=video_task_id,
            asset_format=asset_format,
            filename=filename or path.name,
        )
        uploaded = await self._client.upload_file(
            object_key=object_key,
            file_path=path,
            content_type=content_type,
            presign=presign,
            cache_control=cache_control,
        )
        logger.info(
            "Uploaded video file %s (%s bytes, %s, cache=%s) → %s",
            asset_format.value,
            size,
            content_type,
            cache_control,
            object_key,
        )
        return VideoUploadResult(
            format=asset_format,
            object_key=uploaded.object_key,
            content_type=content_type,
            size_bytes=size,
            presigned_url=uploaded.presigned_url,
            etag=uploaded.etag,
        )

    async def generate_presigned_url(
        self,
        object_key: str,
        *,
        expires_in: int | None = None,
    ) -> str:
        """Create a temporary GET URL for a private video object."""

        if not object_key or not object_key.strip():
            raise ValueError("object_key must not be empty.")
        return await self._client.generate_presigned_url(
            object_key=object_key.strip(),
            expires_in=expires_in,
        )

    async def presign_asset_urls(
        self,
        *,
        file_mp4_url: str | None = None,
        file_webp_url: str | None = None,
        file_gif_url: str | None = None,
        expires_in: int | None = None,
    ) -> VideoPresignedUrls:
        """Presign every non-empty asset key for safe frontend download."""

        async def _maybe(key: str | None) -> str | None:
            if key is None or not key.strip():
                return None
            if key.startswith("http://") or key.startswith("https://"):
                return key
            return await self.generate_presigned_url(key, expires_in=expires_in)

        return VideoPresignedUrls(
            mp4=await _maybe(file_mp4_url),
            webp=await _maybe(file_webp_url),
            gif=await _maybe(file_gif_url),
        )

    async def delete_object(self, object_key: str) -> None:
        """Idempotently delete one stored video object (rollback / cleanup)."""

        if not object_key or not object_key.strip():
            return
        if object_key.startswith("http://") or object_key.startswith("https://"):
            return
        await self._client.delete_object(object_key=object_key.strip())


def get_video_asset_uploader(
    client: SelectelS3Storage | None = None,
) -> VideoAssetUploader:
    """Factory for the 360° video asset uploader."""

    return VideoAssetUploader(client=client)
