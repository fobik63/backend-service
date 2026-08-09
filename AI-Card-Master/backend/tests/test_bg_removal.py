"""Unit tests for product background removal (rembg + billing)."""

from __future__ import annotations

import io
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import numpy as np
import pytest
from PIL import Image, ImageDraw

from app.services.bg_removal import (
    BG_REMOVAL_COST_COINS,
    BackgroundRemovalEngine,
    BackgroundRemovalEngineError,
    BackgroundRemovalService,
    BackgroundRemovalValidationError,
    defringe_edge_colors,
    refine_alpha_edges,
    remove_background,
)
from app.services.billing_service import BillingValidationError
from app.services.s3_storage import S3UploadResult


def _product_png(*, size: int = 64, with_bg: bool = True) -> bytes:
    if with_bg:
        image = Image.new("RGB", (size, size), (240, 240, 245))
    else:
        image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    margin = size // 5
    draw.ellipse(
        (margin, margin, size - margin, size - margin),
        fill=(30, 120, 220) if image.mode == "RGB" else (30, 120, 220, 255),
    )
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _fake_remover(image_bytes: bytes, **_: object) -> bytes:
    """Deterministic stand-in for rembg: keep non-white pixels, add alpha."""

    with Image.open(io.BytesIO(image_bytes)) as src:
        src.load()
        rgba = src.convert("RGBA")
        pixels = rgba.load()
        assert pixels is not None
        width, height = rgba.size
        for y in range(height):
            for x in range(width):
                r, g, b, _a = pixels[x, y]
                # Near-white background → transparent.
                if r > 220 and g > 220 and b > 220:
                    pixels[x, y] = (r, g, b, 0)
                else:
                    pixels[x, y] = (r, g, b, 255)
        out = io.BytesIO()
        rgba.save(out, format="PNG")
        return out.getvalue()


def test_remove_background_returns_png_with_alpha() -> None:
    rembg_stub = MagicMock()
    rembg_stub.remove = _fake_remover
    with patch.dict("sys.modules", {"rembg": rembg_stub}):
        result = remove_background(_product_png())

    assert result.startswith(b"\x89PNG")
    with Image.open(io.BytesIO(result)) as image:
        assert image.mode == "RGBA"
        assert image.size == (64, 64)
        alpha = image.getchannel("A")
        extrema = alpha.getextrema()
        assert extrema[0] == 0
        assert extrema[1] == 255


def test_remove_background_rejects_empty() -> None:
    with pytest.raises(BackgroundRemovalEngineError, match="empty"):
        remove_background(b"")


def test_refine_alpha_edges_erodes_perimeter_junk() -> None:
    rgba = np.zeros((32, 32, 4), dtype=np.uint8)
    rgba[8:24, 8:24] = (200, 200, 200, 255)
    # White dust speck on the silhouette edge.
    rgba[8, 15] = (255, 255, 255, 255)
    cleaned = refine_alpha_edges(rgba, erode_px=2, edge_blur_sigma=0.5)
    assert cleaned[8, 15, 3] < 255
    # Interior stays opaque.
    assert cleaned[16, 16, 3] == 255


def test_defringe_replaces_fringe_with_interior_color() -> None:
    rgba = np.zeros((24, 24, 4), dtype=np.uint8)
    # Solid blue product core.
    rgba[6:18, 6:18] = (20, 80, 200, 255)
    # Semi-transparent fringe contaminated with white background.
    rgba[5, 6:18] = (255, 255, 255, 120)
    # Opaque rim also contaminated (common rembg halo).
    rgba[6, 6:18] = (250, 250, 250, 255)
    cleaned = defringe_edge_colors(
        rgba, solid_alpha=250, interior_inset_px=2, max_radius=6
    )
    fringe_rgb = cleaned[5, 12, :3]
    rim_rgb = cleaned[6, 12, :3]
    assert int(fringe_rgb[2]) > int(fringe_rgb[0])  # bluish, not white
    assert int(rim_rgb[2]) > int(rim_rgb[0])
    assert cleaned[5, 12, 3] == 120
    assert cleaned[16, 16, 3] == 255


@pytest.mark.asyncio
async def test_engine_process_with_injected_remover() -> None:
    engine = BackgroundRemovalEngine(remover=_fake_remover)
    result = await engine.process(_product_png())
    assert result.width == 64
    assert result.height == 64
    assert result.image_png.startswith(b"\x89PNG")


@pytest.mark.asyncio
async def test_bg_removal_service_charges_one_coin() -> None:
    user_id = uuid4()
    user = SimpleNamespace(id=user_id, ai_coins=9)

    session = AsyncMock()
    session.commit = AsyncMock()

    billing = MagicMock()
    billing.debit_coins_in_transaction = AsyncMock(return_value=user)
    billing.refund_coins_in_transaction = AsyncMock()

    storage = MagicMock()
    storage.upload_bytes = AsyncMock(
        return_value=S3UploadResult(
            bucket="test-bucket",
            object_key=f"bg_removal/{user_id}/out.png",
            etag="abc",
            presigned_url="https://cdn.example/cutout.png",
        )
    )

    engine = BackgroundRemovalEngine(remover=_fake_remover)
    service = BackgroundRemovalService(
        session,
        engine=engine,
        billing=billing,
        storage=storage,
    )

    result = await service.process(
        user_id=user_id,
        image_bytes=_product_png(),
    )

    billing.debit_coins_in_transaction.assert_awaited_once()
    debit_kwargs = billing.debit_coins_in_transaction.await_args.kwargs
    assert debit_kwargs["user_id"] == user_id
    assert debit_kwargs["amount"] == BG_REMOVAL_COST_COINS
    assert BG_REMOVAL_COST_COINS == 1
    storage.upload_bytes.assert_awaited_once()
    upload_kwargs = storage.upload_bytes.await_args.kwargs
    assert upload_kwargs["content_type"] == "image/png"
    assert upload_kwargs["object_key"].startswith(f"bg_removal/{user_id}/")
    session.commit.assert_awaited_once()
    assert result.coins_charged == 1
    assert result.new_balance == 9
    assert result.cdn_url == "https://cdn.example/cutout.png"
    billing.refund_coins_in_transaction.assert_not_awaited()


@pytest.mark.asyncio
async def test_bg_removal_service_accepts_image_url() -> None:
    user_id = uuid4()
    user = SimpleNamespace(id=user_id, ai_coins=3)

    session = AsyncMock()
    session.commit = AsyncMock()
    billing = MagicMock()
    billing.debit_coins_in_transaction = AsyncMock(return_value=user)
    billing.refund_coins_in_transaction = AsyncMock()
    storage = MagicMock()
    storage.upload_bytes = AsyncMock(
        return_value=S3UploadResult(
            bucket="test-bucket",
            object_key=f"bg_removal/{user_id}/url.png",
            etag=None,
            presigned_url="https://cdn.example/from-url.png",
        )
    )

    service = BackgroundRemovalService(
        session,
        engine=BackgroundRemovalEngine(remover=_fake_remover),
        billing=billing,
        storage=storage,
    )
    service._download_image = AsyncMock(return_value=_product_png())  # type: ignore[method-assign]

    result = await service.process(
        user_id=user_id,
        image_url="https://cdn.example/product.png",
    )
    assert result.cdn_url == "https://cdn.example/from-url.png"
    service._download_image.assert_awaited_once()


@pytest.mark.asyncio
async def test_bg_removal_service_refunds_on_engine_failure() -> None:
    user_id = uuid4()
    user = SimpleNamespace(id=user_id, ai_coins=5)

    session = AsyncMock()
    billing = MagicMock()
    billing.debit_coins_in_transaction = AsyncMock(return_value=user)
    billing.refund_coins_in_transaction = AsyncMock(return_value=user)

    engine = MagicMock()
    engine.process = AsyncMock(
        side_effect=BackgroundRemovalEngineError("onnx boom")
    )

    service = BackgroundRemovalService(
        session,
        engine=engine,
        billing=billing,
        storage=MagicMock(),
    )

    with pytest.raises(BackgroundRemovalEngineError):
        await service.process(user_id=user_id, image_bytes=_product_png())

    billing.refund_coins_in_transaction.assert_awaited_once()
    refund_kwargs = billing.refund_coins_in_transaction.await_args.kwargs
    assert refund_kwargs["amount"] == 1


@pytest.mark.asyncio
async def test_bg_removal_insufficient_balance() -> None:
    user_id = uuid4()
    session = AsyncMock()
    billing = MagicMock()
    billing.debit_coins_in_transaction = AsyncMock(
        side_effect=BillingValidationError("Insufficient AI-coin balance.")
    )

    service = BackgroundRemovalService(
        session,
        billing=billing,
        storage=MagicMock(),
        engine=BackgroundRemovalEngine(remover=_fake_remover),
    )

    with pytest.raises(BillingValidationError, match="Insufficient"):
        await service.process(user_id=user_id, image_bytes=_product_png())


@pytest.mark.asyncio
async def test_bg_removal_requires_image_source() -> None:
    service = BackgroundRemovalService(
        AsyncMock(),
        billing=MagicMock(),
        storage=MagicMock(),
    )
    with pytest.raises(BackgroundRemovalValidationError, match="Provide"):
        await service.process(user_id=uuid4())
