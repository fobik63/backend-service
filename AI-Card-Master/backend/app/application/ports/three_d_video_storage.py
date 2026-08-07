"""Application port for 360° video asset storage (S3/MinIO)."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol
from uuid import UUID

from app.domain.three_d_video import VIDEO_ASSET_CACHE_CONTROL
from app.domain.three_d_video import (
    VideoAssetFormat,
    VideoPresignedUrls,
    VideoUploadResult,
)


class VideoAssetUploaderPort(Protocol):
    """Bounded storage operations for orbital video binaries."""

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
    ) -> VideoUploadResult: ...

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
    ) -> VideoUploadResult: ...

    async def generate_presigned_url(
        self,
        object_key: str,
        *,
        expires_in: int | None = None,
    ) -> str: ...

    async def presign_asset_urls(
        self,
        *,
        file_mp4_url: str | None = None,
        file_webp_url: str | None = None,
        file_gif_url: str | None = None,
        expires_in: int | None = None,
    ) -> VideoPresignedUrls: ...

    async def delete_object(self, object_key: str) -> None: ...
