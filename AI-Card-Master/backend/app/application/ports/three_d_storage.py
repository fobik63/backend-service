"""Application port for 3D object storage (S3/MinIO)."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol
from uuid import UUID

from app.domain.three_d import (
    ThreeDAssetFormat,
    ThreeDPresignedUrls,
    ThreeDUploadResult,
)


class ThreeDObjectStoragePort(Protocol):
    """Bounded storage operations for heavy 3D binaries."""

    async def upload_bytes(
        self,
        *,
        user_id: UUID,
        task_id: UUID,
        asset_format: ThreeDAssetFormat,
        data: bytes,
        filename: str | None = None,
        presign: bool = True,
    ) -> ThreeDUploadResult: ...

    async def upload_file(
        self,
        *,
        user_id: UUID,
        task_id: UUID,
        asset_format: ThreeDAssetFormat,
        file_path: str | Path,
        filename: str | None = None,
        presign: bool = True,
    ) -> ThreeDUploadResult: ...

    async def generate_presigned_url(
        self,
        object_key: str,
        *,
        expires_in: int | None = None,
    ) -> str: ...

    async def presign_asset_urls(
        self,
        *,
        file_glb_url: str | None = None,
        file_usdz_url: str | None = None,
        file_obj_url: str | None = None,
        preview_png_url: str | None = None,
        thumbnail_url: str | None = None,
        expires_in: int | None = None,
    ) -> ThreeDPresignedUrls: ...

    async def delete_object(self, object_key: str) -> None: ...

    async def download_bytes(self, *, object_key: str, max_bytes: int) -> bytes: ...
