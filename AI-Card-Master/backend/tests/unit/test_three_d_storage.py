"""Unit tests for 3D S3 storage helper and domain content-type map."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest

from app.domain.three_d import (
    THREE_D_CONTENT_TYPES,
    GpuRentalSessionStatus,
    ThreeDAssetFormat,
    ThreeDInputType,
    ThreeDTaskStatus,
)
from app.services.s3_storage import S3UploadResult
from app.services.three_d.storage import ThreeDObjectStorage


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
    ) -> S3UploadResult:
        self.uploads.append(
            {
                "object_key": object_key,
                "data": data,
                "content_type": content_type,
                "presign": presign,
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
    ) -> S3UploadResult:
        self.file_uploads.append(
            {
                "object_key": object_key,
                "file_path": str(file_path),
                "content_type": content_type,
                "presign": presign,
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
def storage() -> tuple[ThreeDObjectStorage, _FakeS3]:
    fake = _FakeS3()
    return ThreeDObjectStorage(client=fake), fake


def test_content_types_match_3d_mime_standards() -> None:
    assert THREE_D_CONTENT_TYPES[ThreeDAssetFormat.GLB] == "model/gltf-binary"
    assert THREE_D_CONTENT_TYPES[ThreeDAssetFormat.USDZ] == "model/vnd.usdz+zip"
    assert THREE_D_CONTENT_TYPES[ThreeDAssetFormat.OBJ] == "model/obj"
    assert THREE_D_CONTENT_TYPES[ThreeDAssetFormat.PREVIEW_PNG] == "image/png"


def test_domain_status_enums() -> None:
    assert ThreeDTaskStatus.PENDING.value == "PENDING"
    assert ThreeDTaskStatus.CANCELED.value == "CANCELED"
    assert ThreeDInputType.TEXT_TO_3D.value == "TEXT_TO_3D"
    assert ThreeDInputType.IMAGE_TO_3D.value == "IMAGE_TO_3D"
    assert GpuRentalSessionStatus.RUNNING.value == "RUNNING"


def test_build_object_key_is_namespaced() -> None:
    user_id = uuid4()
    task_id = uuid4()
    key = ThreeDObjectStorage.build_object_key(
        user_id=user_id,
        task_id=task_id,
        asset_format=ThreeDAssetFormat.GLB,
    )
    assert key == f"three-d/{user_id}/{task_id}/glb.glb"

    custom = ThreeDObjectStorage.build_object_key(
        user_id=user_id,
        task_id=task_id,
        asset_format=ThreeDAssetFormat.USDZ,
        filename="Product Mesh.usdz",
    )
    assert custom == f"three-d/{user_id}/{task_id}/Product-Mesh.usdz"


@pytest.mark.asyncio
async def test_upload_bytes_sets_glb_content_type(
    storage: tuple[ThreeDObjectStorage, _FakeS3],
) -> None:
    helper, fake = storage
    user_id = uuid4()
    task_id = uuid4()
    payload = b"glTF-binary-payload"

    result = await helper.upload_bytes(
        user_id=user_id,
        task_id=task_id,
        asset_format=ThreeDAssetFormat.GLB,
        data=payload,
    )

    assert result.content_type == "model/gltf-binary"
    assert result.size_bytes == len(payload)
    assert result.object_key.endswith("/glb.glb")
    assert result.presigned_url.startswith("https://cdn.test/")
    assert fake.uploads[0]["content_type"] == "model/gltf-binary"


@pytest.mark.asyncio
async def test_upload_file_sets_usdz_content_type(
    storage: tuple[ThreeDObjectStorage, _FakeS3],
    tmp_path: Path,
) -> None:
    helper, fake = storage
    path = tmp_path / "model.usdz"
    path.write_bytes(b"usdz-zip-bytes")

    result = await helper.upload_file(
        user_id=uuid4(),
        task_id=uuid4(),
        asset_format=ThreeDAssetFormat.USDZ,
        file_path=path,
    )

    assert result.content_type == "model/vnd.usdz+zip"
    assert result.size_bytes == len(b"usdz-zip-bytes")
    assert fake.file_uploads[0]["content_type"] == "model/vnd.usdz+zip"


@pytest.mark.asyncio
async def test_presign_asset_urls_skips_external_cdn(
    storage: tuple[ThreeDObjectStorage, _FakeS3],
) -> None:
    helper, _fake = storage
    urls = await helper.presign_asset_urls(
        file_glb_url="three-d/u/t/glb.glb",
        file_usdz_url="https://provider.cdn/result.usdz",
        file_obj_url=None,
        preview_png_url="three-d/u/t/preview.png",
        thumbnail_url="",
        expires_in=120,
    )

    assert urls.glb == "https://cdn.test/three-d/u/t/glb.glb?expires=120"
    assert urls.usdz == "https://provider.cdn/result.usdz"
    assert urls.obj is None
    assert urls.preview_png == "https://cdn.test/three-d/u/t/preview.png?expires=120"
    assert urls.thumbnail is None


@pytest.mark.asyncio
async def test_delete_ignores_http_urls(
    storage: tuple[ThreeDObjectStorage, _FakeS3],
) -> None:
    helper, fake = storage
    await helper.delete_object("https://cdn.example/a.glb")
    await helper.delete_object("three-d/u/t/glb.glb")
    assert fake.deleted == ["three-d/u/t/glb.glb"]


@pytest.mark.asyncio
async def test_upload_bytes_rejects_empty(
    storage: tuple[ThreeDObjectStorage, _FakeS3],
) -> None:
    helper, _fake = storage
    with pytest.raises(ValueError, match="empty"):
        await helper.upload_bytes(
            user_id=uuid4(),
            task_id=uuid4(),
            asset_format=ThreeDAssetFormat.OBJ,
            data=b"",
        )
