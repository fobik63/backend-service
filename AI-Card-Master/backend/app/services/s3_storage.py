"""Selectel S3-compatible object storage (upload + presigned download URLs)."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import boto3
from boto3.s3.transfer import TransferConfig
from botocore.client import BaseClient
from botocore.config import Config

from app.core.config import Settings, get_settings

logger = logging.getLogger(__name__)


class S3StorageError(Exception):
    """Base Selectel/S3 storage failure."""


class S3StorageConfigurationError(S3StorageError):
    """Missing S3 credentials or bucket settings."""


@dataclass(frozen=True, slots=True)
class S3UploadResult:
    """Result of uploading an object to Selectel S3."""

    bucket: str
    object_key: str
    etag: str | None
    presigned_url: str


class SelectelS3Storage:
    """Async-friendly wrapper around boto3 S3 client for Selectel."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        access_key = (self._settings.s3_access_key_id or "").strip()
        secret = (
            self._settings.s3_secret_access_key.get_secret_value().strip()
            if self._settings.s3_secret_access_key is not None
            else ""
        )
        bucket = (self._settings.s3_bucket_name or "").strip()
        endpoint = (self._settings.s3_endpoint_url or "").strip()
        if not access_key or not secret or not bucket or not endpoint:
            raise S3StorageConfigurationError(
                "S3_ACCESS_KEY_ID, S3_SECRET_ACCESS_KEY, S3_BUCKET_NAME, "
                "and S3_ENDPOINT_URL must be configured for Selectel."
            )
        self._bucket = bucket
        self._endpoint = endpoint.rstrip("/")
        self._region = self._settings.s3_region
        self._presign_ttl = self._settings.s3_presign_ttl_seconds
        self._client: BaseClient = boto3.client(
            "s3",
            endpoint_url=self._endpoint,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret,
            region_name=self._region,
            config=Config(
                signature_version="s3v4",
                s3={"addressing_style": self._settings.s3_addressing_style},
            ),
        )

    async def upload_bytes(
        self,
        *,
        object_key: str,
        data: bytes,
        content_type: str,
        presign: bool = True,
        cache_control: str | None = None,
    ) -> S3UploadResult:
        """Upload bytes to the configured bucket and optionally return a presigned URL."""

        if not object_key.strip():
            raise S3StorageError("object_key must not be empty.")
        if not data:
            raise S3StorageError("Cannot upload empty payload.")

        def _put() -> dict[str, Any]:
            kwargs: dict[str, Any] = {
                "Bucket": self._bucket,
                "Key": object_key,
                "Body": data,
                "ContentType": content_type,
            }
            if cache_control is not None and cache_control.strip():
                kwargs["CacheControl"] = cache_control.strip()
            return self._client.put_object(**kwargs)

        try:
            response = await asyncio.to_thread(_put)
        except Exception as exc:
            raise S3StorageError(f"S3 upload failed for key '{object_key}': {exc}") from exc

        etag = response.get("ETag")
        if isinstance(etag, str):
            etag = etag.strip('"')
        else:
            etag = None

        presigned_url = ""
        if presign:
            presigned_url = await self.generate_presigned_url(object_key=object_key)

        logger.info(
            "Uploaded object s3://%s/%s (%s bytes)",
            self._bucket,
            object_key,
            len(data),
        )
        return S3UploadResult(
            bucket=self._bucket,
            object_key=object_key,
            etag=etag,
            presigned_url=presigned_url,
        )

    async def upload_file(
        self,
        *,
        object_key: str,
        file_path: str | Path,
        content_type: str,
        presign: bool = True,
        cache_control: str | None = None,
    ) -> S3UploadResult:
        """Multipart-upload a local file without loading the whole payload into RAM."""

        if not object_key.strip():
            raise S3StorageError("object_key must not be empty.")
        path = Path(file_path)

        def _inspect_path() -> tuple[bool, int]:
            if not path.is_file():
                return False, 0
            return True, path.stat().st_size

        try:
            is_file, size = await asyncio.to_thread(_inspect_path)
        except OSError as exc:
            raise S3StorageError(f"Cannot inspect upload path: {path}") from exc
        if not is_file:
            raise S3StorageError(f"Upload path is not a file: {path}")
        if size <= 0:
            raise S3StorageError("Cannot upload empty file.")

        transfer_config = TransferConfig(
            multipart_threshold=8 * 1024 * 1024,
            multipart_chunksize=8 * 1024 * 1024,
            max_concurrency=4,
            use_threads=True,
        )
        extra_args: dict[str, str] = {"ContentType": content_type}
        if cache_control is not None and cache_control.strip():
            extra_args["CacheControl"] = cache_control.strip()

        def _upload() -> dict[str, Any]:
            self._client.upload_file(
                Filename=str(path),
                Bucket=self._bucket,
                Key=object_key,
                ExtraArgs=extra_args,
                Config=transfer_config,
            )
            return self._client.head_object(Bucket=self._bucket, Key=object_key)

        try:
            head = await asyncio.to_thread(_upload)
        except Exception as exc:
            raise S3StorageError(
                f"S3 multipart upload failed for key '{object_key}': {exc}"
            ) from exc

        etag = head.get("ETag")
        if isinstance(etag, str):
            etag = etag.strip('"')
        else:
            etag = None

        presigned_url = ""
        if presign:
            presigned_url = await self.generate_presigned_url(object_key=object_key)

        logger.info(
            "Uploaded file s3://%s/%s (%s bytes, multipart-capable)",
            self._bucket,
            object_key,
            size,
        )
        return S3UploadResult(
            bucket=self._bucket,
            object_key=object_key,
            etag=etag,
            presigned_url=presigned_url,
        )

    async def generate_presigned_url(
        self,
        *,
        object_key: str,
        expires_in: int | None = None,
    ) -> str:
        """Create a temporary GET URL for a private object."""

        ttl = expires_in if expires_in is not None else self._presign_ttl
        if ttl <= 0:
            raise S3StorageError("Presign TTL must be positive.")

        def _presign() -> str:
            return self._client.generate_presigned_url(
                "get_object",
                Params={"Bucket": self._bucket, "Key": object_key},
                ExpiresIn=ttl,
            )

        try:
            url = await asyncio.to_thread(_presign)
        except Exception as exc:
            raise S3StorageError(
                f"Failed to create presigned URL for '{object_key}': {exc}"
            ) from exc
        return url

    async def download_bytes(self, *, object_key: str, max_bytes: int) -> bytes:
        """Download one object with a hard byte limit."""

        if not object_key.strip():
            raise S3StorageError("object_key must not be empty.")
        if max_bytes <= 0:
            raise S3StorageError("max_bytes must be positive.")

        def _get() -> bytes:
            response = self._client.get_object(Bucket=self._bucket, Key=object_key)
            body = response["Body"]
            try:
                data = body.read(max_bytes + 1)
            finally:
                body.close()
            return data

        try:
            data = await asyncio.to_thread(_get)
        except Exception as exc:
            raise S3StorageError(f"S3 download failed for key '{object_key}': {exc}") from exc
        if not data:
            raise S3StorageError(f"S3 object '{object_key}' is empty.")
        if len(data) > max_bytes:
            raise S3StorageError(
                f"S3 object '{object_key}' exceeds the {max_bytes}-byte limit."
            )
        return data

    async def healthcheck(self) -> bool:
        """Check bucket access without listing or exposing object metadata."""

        try:
            await asyncio.to_thread(self._client.head_bucket, Bucket=self._bucket)
            return True
        except Exception:
            logger.warning("S3 health check failed", exc_info=True)
            return False

    async def delete_object(self, *, object_key: str) -> None:
        """Idempotently delete an object, primarily for failed job creation."""

        if not object_key.strip():
            return
        try:
            await asyncio.to_thread(
                self._client.delete_object,
                Bucket=self._bucket,
                Key=object_key,
            )
        except Exception as exc:
            raise S3StorageError(f"S3 delete failed for key '{object_key}': {exc}") from exc

    async def aclose(self) -> None:
        """Close the underlying boto3 HTTP pool."""

        close = getattr(self._client, "close", None)
        if callable(close):
            await asyncio.to_thread(close)

    # ObjectStoragePort aliases used by Clean Architecture application services.
    async def upload(self, *, object_key: str, data: bytes, content_type: str) -> None:
        await self.upload_bytes(
            object_key=object_key,
            data=data,
            content_type=content_type,
            presign=False,
        )

    async def download(self, object_key: str, *, max_bytes: int) -> bytes:
        return await self.download_bytes(object_key=object_key, max_bytes=max_bytes)

    async def presign(self, object_key: str) -> str:
        return await self.generate_presigned_url(object_key=object_key)


@lru_cache(maxsize=1)
def get_s3_storage() -> SelectelS3Storage:
    """Cached Selectel S3 storage client."""

    return SelectelS3Storage()


async def close_s3_storage() -> None:
    """Close the cached client when configured and clear the singleton."""

    if get_s3_storage.cache_info().currsize:
        storage = get_s3_storage()
        await storage.aclose()
        get_s3_storage.cache_clear()
