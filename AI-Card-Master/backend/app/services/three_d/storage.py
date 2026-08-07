"""S3/MinIO helper for heavy 3D binaries with correct Content-Type + presign."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Protocol
from uuid import UUID

from app.domain.three_d import (
    THREE_D_CONTENT_TYPES,
    THREE_D_FILE_EXTENSIONS,
    ThreeDAssetFormat,
    ThreeDPresignedUrls,
    ThreeDUploadResult,
)
from app.services.s3_storage import S3UploadResult, SelectelS3Storage, get_s3_storage

logger = logging.getLogger(__name__)

_KEY_PREFIX = "three-d"

# Re-export domain DTOs for callers that import from this module.
__all__ = [
    "ThreeDObjectStorage",
    "ThreeDPresignedUrls",
    "ThreeDUploadResult",
    "get_three_d_object_storage",
]


class _ThreeDS3Client(Protocol):
    """Minimal S3 surface used by ThreeDObjectStorage (testable)."""

    async def upload_bytes(
        self,
        *,
        object_key: str,
        data: bytes,
        content_type: str,
        presign: bool = True,
    ) -> S3UploadResult: ...

    async def upload_file(
        self,
        *,
        object_key: str,
        file_path: str | Path,
        content_type: str,
        presign: bool = True,
    ) -> S3UploadResult: ...

    async def generate_presigned_url(
        self,
        *,
        object_key: str,
        expires_in: int | None = None,
    ) -> str: ...

    async def delete_object(self, *, object_key: str) -> None: ...


class ThreeDObjectStorage:
    """Upload/download helper specialized for 3D mesh + texture binaries.

    Stores objects under ``three-d/{user_id}/{task_id}/…`` with MIME types:
    - GLB  → ``model/gltf-binary``
    - USDZ → ``model/vnd.usdz+zip``
    - OBJ  → ``model/obj``
    - PNG  → ``image/png``
    """

    def __init__(self, client: _ThreeDS3Client | None = None) -> None:
        self._client: _ThreeDS3Client = client or get_s3_storage()

    @staticmethod
    def content_type_for(asset_format: ThreeDAssetFormat) -> str:
        return THREE_D_CONTENT_TYPES[asset_format]

    @staticmethod
    def build_object_key(
        *,
        user_id: UUID,
        task_id: UUID,
        asset_format: ThreeDAssetFormat,
        filename: str | None = None,
    ) -> str:
        """Build a deterministic, namespaced object key for a 3D asset."""

        ext = THREE_D_FILE_EXTENSIONS[asset_format]
        if filename is not None and filename.strip():
            stem = Path(filename.strip()).stem or asset_format.value
            safe_stem = "".join(
                ch if ch.isalnum() or ch in {"-", "_"} else "-" for ch in stem
            ).strip("-") or asset_format.value
            return f"{_KEY_PREFIX}/{user_id}/{task_id}/{safe_stem}.{ext}"
        return f"{_KEY_PREFIX}/{user_id}/{task_id}/{asset_format.value}.{ext}"

    async def upload_bytes(
        self,
        *,
        user_id: UUID,
        task_id: UUID,
        asset_format: ThreeDAssetFormat,
        data: bytes,
        filename: str | None = None,
        presign: bool = True,
    ) -> ThreeDUploadResult:
        """Upload an in-memory 3D binary with the correct Content-Type."""

        if not data:
            raise ValueError("Cannot upload empty 3D payload.")
        content_type = self.content_type_for(asset_format)
        object_key = self.build_object_key(
            user_id=user_id,
            task_id=task_id,
            asset_format=asset_format,
            filename=filename,
        )
        uploaded = await self._client.upload_bytes(
            object_key=object_key,
            data=data,
            content_type=content_type,
            presign=presign,
        )
        logger.info(
            "Uploaded 3D %s (%s bytes, %s) → %s",
            asset_format.value,
            len(data),
            content_type,
            object_key,
        )
        return ThreeDUploadResult(
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
        task_id: UUID,
        asset_format: ThreeDAssetFormat,
        file_path: str | Path,
        filename: str | None = None,
        presign: bool = True,
    ) -> ThreeDUploadResult:
        """Multipart-upload a large local 3D file without loading it into RAM."""

        path = Path(file_path)
        if not path.is_file():
            raise ValueError(f"Upload path is not a file: {path}")
        size = path.stat().st_size
        if size <= 0:
            raise ValueError("Cannot upload empty 3D file.")
        content_type = self.content_type_for(asset_format)
        object_key = self.build_object_key(
            user_id=user_id,
            task_id=task_id,
            asset_format=asset_format,
            filename=filename or path.name,
        )
        uploaded = await self._client.upload_file(
            object_key=object_key,
            file_path=path,
            content_type=content_type,
            presign=presign,
        )
        logger.info(
            "Uploaded 3D file %s (%s bytes, %s) → %s",
            asset_format.value,
            size,
            content_type,
            object_key,
        )
        return ThreeDUploadResult(
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
        """Create a temporary GET URL for a private 3D object."""

        if not object_key or not object_key.strip():
            raise ValueError("object_key must not be empty.")
        return await self._client.generate_presigned_url(
            object_key=object_key.strip(),
            expires_in=expires_in,
        )

    async def presign_asset_urls(
        self,
        *,
        file_glb_url: str | None = None,
        file_usdz_url: str | None = None,
        file_obj_url: str | None = None,
        preview_png_url: str | None = None,
        thumbnail_url: str | None = None,
        expires_in: int | None = None,
    ) -> ThreeDPresignedUrls:
        """Presign every non-empty asset key for frontend download/AR viewers."""

        async def _maybe(key: str | None) -> str | None:
            if key is None or not key.strip():
                return None
            # External CDN URLs (provider fixtures) are returned as-is.
            if key.startswith("http://") or key.startswith("https://"):
                return key
            return await self.generate_presigned_url(key, expires_in=expires_in)

        return ThreeDPresignedUrls(
            glb=await _maybe(file_glb_url),
            usdz=await _maybe(file_usdz_url),
            obj=await _maybe(file_obj_url),
            preview_png=await _maybe(preview_png_url),
            thumbnail=await _maybe(thumbnail_url),
        )

    async def delete_object(self, object_key: str) -> None:
        """Idempotently delete one stored 3D object (rollback / cleanup)."""

        if not object_key or not object_key.strip():
            return
        if object_key.startswith("http://") or object_key.startswith("https://"):
            return
        await self._client.delete_object(object_key=object_key.strip())


def get_three_d_object_storage(
    client: SelectelS3Storage | None = None,
) -> ThreeDObjectStorage:
    """Factory for the 3D-specialized object storage helper."""

    return ThreeDObjectStorage(client=client)
