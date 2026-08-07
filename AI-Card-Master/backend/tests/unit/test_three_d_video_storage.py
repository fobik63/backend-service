"""Unit tests for 360° video S3 uploader and domain content-type map."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest

from app.domain.three_d_video import (
    VIDEO_ASSET_CACHE_CONTROL,
    VIDEO_ASSET_CACHE_MAX_AGE_SECONDS,
    VIDEO_CONTENT_TYPES,
    ThreeDVideoTaskStatus,
    VideoAssetFormat,
    VideoBackgroundType,
    parse_background_type,
    parse_resolution,
    parse_rotation_direction,
)
from app.services.s3_storage import S3UploadResult
from app.services.three_d.video_storage import VideoAssetUploader


class _FakeS3:
    def __init__(self) -> None:
        self.uploads: list[dict[str, object]] = []
        self.file_uploads: list[dict[str, object]] = []
        self.deleted: list[str] = []

    async def upload_bytes(
        self,
        *,
        object_key: str,
        data: bytes,
        content_type: str,
        presign: bool = True,
        cache_control: str | None = None,
    ) -> S3UploadResult:
        self.uploads.append(
            {
                "object_key": object_key,
                "data": data,
                "content_type": content_type,
                "presign": presign,
                "cache_control": cache_control,
            }
        )
        return S3UploadResult(
            bucket="test-bucket",
            object_key=object_key,
            etag="etag-bytes",
            presigned_url=f"https://cdn.test/{object_key}?sig=1" if presign else "",
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
        self.file_uploads.append(
            {
                "object_key": object_key,
                "file_path": str(file_path),
                "content_type": content_type,
                "presign": presign,
                "cache_control": cache_control,
            }
        )
        return S3UploadResult(
            bucket="test-bucket",
            object_key=object_key,
            etag="etag-file",
            presigned_url=f"https://cdn.test/{object_key}?sig=1" if presign else "",
        )

    async def generate_presigned_url(
        self,
        *,
        object_key: str,
        expires_in: int | None = None,
    ) -> str:
        ttl = expires_in if expires_in is not None else 3600
        return f"https://cdn.test/{object_key}?expires={ttl}"

    async def delete_object(self, *, object_key: str) -> None:
        self.deleted.append(object_key)


@pytest.fixture
def uploader() -> tuple[VideoAssetUploader, _FakeS3]:
    fake = _FakeS3()
    return VideoAssetUploader(client=fake), fake


def test_content_types_match_video_mime_standards() -> None:
    assert VIDEO_CONTENT_TYPES[VideoAssetFormat.MP4] == "video/mp4"
    assert VIDEO_CONTENT_TYPES[VideoAssetFormat.WEBP] == "image/webp"
    assert VIDEO_CONTENT_TYPES[VideoAssetFormat.GIF] == "image/gif"


def test_cache_control_is_one_year_immutable() -> None:
    assert "31536000" in VIDEO_ASSET_CACHE_CONTROL
    assert VIDEO_ASSET_CACHE_MAX_AGE_SECONDS == 31_536_000
    assert "immutable" in VIDEO_ASSET_CACHE_CONTROL


def test_domain_status_and_background_enums() -> None:
    assert ThreeDVideoTaskStatus.QUEUED.value == "QUEUED"
    assert ThreeDVideoTaskStatus.RENDERING.value == "RENDERING"
    assert ThreeDVideoTaskStatus.ENCODING.value == "ENCODING"
    assert VideoBackgroundType.TRANSPARENT.value == "TRANSPARENT"
    assert parse_background_type("gradient") is VideoBackgroundType.GRADIENT
    assert parse_rotation_direction("ccw").value == "counter_clockwise"
    assert parse_resolution("1080x1440") == "1080x1440"


@pytest.mark.asyncio
async def test_upload_bytes_sets_content_type_and_cache_control(
    uploader: tuple[VideoAssetUploader, _FakeS3],
) -> None:
    storage, fake = uploader
    user_id = uuid4()
    video_task_id = uuid4()
    payload = b"fake-mp4-bytes"

    result = await storage.upload_bytes(
        user_id=user_id,
        video_task_id=video_task_id,
        asset_format=VideoAssetFormat.MP4,
        data=payload,
    )

    assert result.content_type == "video/mp4"
    assert result.size_bytes == len(payload)
    assert result.presigned_url.startswith("https://cdn.test/")
    assert len(fake.uploads) == 1
    assert fake.uploads[0]["content_type"] == "video/mp4"
    assert fake.uploads[0]["cache_control"] == VIDEO_ASSET_CACHE_CONTROL
    assert fake.uploads[0]["object_key"] == (
        f"three-d-video/{user_id}/{video_task_id}/mp4.mp4"
    )


@pytest.mark.asyncio
async def test_upload_webp_and_gif_mime_types(
    uploader: tuple[VideoAssetUploader, _FakeS3],
) -> None:
    storage, fake = uploader
    user_id = uuid4()
    video_task_id = uuid4()

    await storage.upload_bytes(
        user_id=user_id,
        video_task_id=video_task_id,
        asset_format=VideoAssetFormat.WEBP,
        data=b"webp",
    )
    await storage.upload_bytes(
        user_id=user_id,
        video_task_id=video_task_id,
        asset_format=VideoAssetFormat.GIF,
        data=b"gif",
    )

    assert fake.uploads[0]["content_type"] == "image/webp"
    assert fake.uploads[1]["content_type"] == "image/gif"
    assert all(
        item["cache_control"] == VIDEO_ASSET_CACHE_CONTROL for item in fake.uploads
    )


@pytest.mark.asyncio
async def test_presign_asset_urls_skips_external_https(
    uploader: tuple[VideoAssetUploader, _FakeS3],
) -> None:
    storage, _fake = uploader
    urls = await storage.presign_asset_urls(
        file_mp4_url="three-d-video/u/t/mp4.mp4",
        file_webp_url="https://cdn.example/preview.webp",
        file_gif_url=None,
        expires_in=120,
    )
    assert urls.mp4 == "https://cdn.test/three-d-video/u/t/mp4.mp4?expires=120"
    assert urls.webp == "https://cdn.example/preview.webp"
    assert urls.gif is None


@pytest.mark.asyncio
async def test_upload_file_passes_cache_control(
    uploader: tuple[VideoAssetUploader, _FakeS3],
    tmp_path: Path,
) -> None:
    storage, fake = uploader
    path = tmp_path / "orbit.mp4"
    path.write_bytes(b"0123456789")

    result = await storage.upload_file(
        user_id=uuid4(),
        video_task_id=uuid4(),
        asset_format=VideoAssetFormat.MP4,
        file_path=path,
    )

    assert result.size_bytes == 10
    assert fake.file_uploads[0]["cache_control"] == VIDEO_ASSET_CACHE_CONTROL
    assert fake.file_uploads[0]["content_type"] == "video/mp4"
