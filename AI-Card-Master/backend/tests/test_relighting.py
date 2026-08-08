"""Unit tests for photostudio relighting (maps + billing)."""

from __future__ import annotations

import io
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from PIL import Image, ImageDraw

from app.services.billing_service import BillingValidationError
from app.services.relighting import (
    RELIGHTING_COST_COINS,
    LIGHTING_PRESETS,
    RelightingEngineService,
    RelightingPresetName,
    RelightingService,
    RelightingValidationError,
    get_lighting_preset,
)
from app.services.relighting.depth_normal import estimate_depth_and_normals
from app.services.relighting.shadows import build_shadow_params, generate_shadow_layer
from app.services.s3_storage import S3UploadResult


def _product_png(*, size: int = 96) -> bytes:
    image = Image.new("RGBA", (size, size), (255, 255, 255, 0))
    draw = ImageDraw.Draw(image)
    margin = size // 5
    draw.rounded_rectangle(
        (margin, margin // 2, size - margin, size - margin // 3),
        radius=max(4, size // 12),
        fill=(210, 40, 55, 255),
    )
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def test_lighting_presets_cover_required_looks() -> None:
    assert set(LIGHTING_PRESETS) == {
        RelightingPresetName.GOLDEN_HOUR,
        RelightingPresetName.CYBERPUNK_NEON,
        RelightingPresetName.DRAMATIC_STUDIO,
        RelightingPresetName.SOFT_COMMERCIAL,
    }
    golden = get_lighting_preset("golden_hour")
    assert golden.color_temperature_k == 3500
    cyber = get_lighting_preset(RelightingPresetName.CYBERPUNK_NEON)
    assert len(cyber.lights) >= 2
    dramatic = get_lighting_preset("dramatic_studio")
    assert dramatic.background_rgb[0] < 40
    soft = get_lighting_preset("soft_commercial")
    assert soft.shadow_opacity < 0.3


def test_estimate_depth_and_normal_maps() -> None:
    maps = estimate_depth_and_normals(_product_png())
    assert maps.width == 96
    assert maps.height == 96
    assert maps.depth_png.startswith(b"\x89PNG")
    assert maps.normal_png.startswith(b"\x89PNG")
    assert maps.mask_png.startswith(b"\x89PNG")

    with Image.open(io.BytesIO(maps.depth_png)) as depth:
        assert depth.mode == "L"
        assert depth.getbbox() is not None
    with Image.open(io.BytesIO(maps.normal_png)) as normals:
        assert normals.mode == "RGB"
        # Camera-facing bias: typical Z channel above mid-grey across the frame.
        z_channel = normals.split()[2]
        hist = z_channel.histogram()
        total = sum(hist) or 1
        avg_z = sum(value * count for value, count in enumerate(hist)) / total
        assert avg_z > 120


def test_shadow_generator_respects_blur_angle_opacity() -> None:
    mask = Image.new("L", (64, 64), 0)
    ImageDraw.Draw(mask).ellipse((16, 12, 48, 52), fill=255)
    params = build_shadow_params(
        blur_px=20,
        angle_deg=40.0,
        opacity=0.8,
        cast_length=0.5,
        shadow_intensity=1.0,
    )
    assert params.blur_px == 20
    assert params.angle_deg == 40.0
    assert params.opacity == pytest.approx(0.8)

    layer = generate_shadow_layer(mask, (64, 64), (0, 0), params)
    assert layer.mode == "RGBA"
    assert layer.getbbox() is not None

    none = build_shadow_params(
        blur_px=20,
        angle_deg=40.0,
        opacity=0.8,
        cast_length=0.5,
        shadow_intensity=0.0,
    )
    assert none.opacity == 0.0


@pytest.mark.asyncio
async def test_engine_process_returns_relit_png() -> None:
    engine = RelightingEngineService()
    maps = await engine.generate_maps(_product_png())
    assert maps.depth_png and maps.normal_png

    result = await engine.process(
        _product_png(),
        preset_name="soft_commercial",
        shadow_intensity=0.5,
    )
    assert result.preset_name is RelightingPresetName.SOFT_COMMERCIAL
    assert result.image_png.startswith(b"\x89PNG")
    assert result.width == 96
    assert result.height == 96


@pytest.mark.asyncio
async def test_relighting_service_charges_five_coins() -> None:
    user_id = uuid4()
    user = SimpleNamespace(id=user_id, ai_coins=20)

    session = AsyncMock()
    session.commit = AsyncMock()

    billing = MagicMock()
    billing.debit_coins_in_transaction = AsyncMock(return_value=user)
    billing.refund_coins_in_transaction = AsyncMock()

    storage = MagicMock()
    storage.upload_bytes = AsyncMock(
        return_value=S3UploadResult(
            bucket="test-bucket",
            object_key=f"relighting/{user_id}/out.png",
            etag="abc",
            presigned_url="https://cdn.example/out.png",
        )
    )

    service = RelightingService(
        session,
        billing=billing,
        storage=storage,
    )
    service._download_image = AsyncMock(return_value=_product_png())  # type: ignore[method-assign]

    result = await service.process(
        user_id=user_id,
        image_url="https://cdn.example/product.png",
        preset_name="golden_hour",
        shadow_intensity=0.8,
    )

    billing.debit_coins_in_transaction.assert_awaited_once()
    debit_kwargs = billing.debit_coins_in_transaction.await_args.kwargs
    assert debit_kwargs["user_id"] == user_id
    assert debit_kwargs["amount"] == RELIGHTING_COST_COINS
    assert RELIGHTING_COST_COINS == 5
    storage.upload_bytes.assert_awaited_once()
    session.commit.assert_awaited_once()
    assert result.coins_charged == 5
    assert result.new_balance == 20
    assert result.result_url == "https://cdn.example/out.png"
    assert result.preset_name is RelightingPresetName.GOLDEN_HOUR
    billing.refund_coins_in_transaction.assert_not_awaited()


@pytest.mark.asyncio
async def test_relighting_service_refunds_on_engine_failure() -> None:
    user_id = uuid4()
    user = SimpleNamespace(id=user_id, ai_coins=10)

    session = AsyncMock()
    billing = MagicMock()
    billing.debit_coins_in_transaction = AsyncMock(return_value=user)
    billing.refund_coins_in_transaction = AsyncMock(return_value=user)

    engine = MagicMock()
    engine.process = AsyncMock(side_effect=RelightingValidationError("boom"))

    service = RelightingService(
        session,
        engine=engine,
        billing=billing,
        storage=MagicMock(),
    )
    service._download_image = AsyncMock(return_value=_product_png())  # type: ignore[method-assign]

    with pytest.raises(RelightingValidationError):
        await service.process(
            user_id=user_id,
            image_url="https://cdn.example/product.png",
            preset_name="cyberpunk_neon",
            shadow_intensity=0.5,
        )

    billing.refund_coins_in_transaction.assert_awaited_once()
    refund_kwargs = billing.refund_coins_in_transaction.await_args.kwargs
    assert refund_kwargs["amount"] == 5


@pytest.mark.asyncio
async def test_relighting_insufficient_balance() -> None:
    user_id = uuid4()
    session = AsyncMock()
    billing = MagicMock()
    billing.debit_coins_in_transaction = AsyncMock(
        side_effect=BillingValidationError("Insufficient AI-coin balance.")
    )

    service = RelightingService(session, billing=billing, storage=MagicMock())
    service._download_image = AsyncMock(return_value=_product_png())  # type: ignore[method-assign]

    with pytest.raises(BillingValidationError, match="Insufficient"):
        await service.process(
            user_id=user_id,
            image_url="https://cdn.example/product.png",
            preset_name="dramatic_studio",
            shadow_intensity=1.0,
        )
