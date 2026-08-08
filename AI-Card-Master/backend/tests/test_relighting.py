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
    StudioLightDTO,
    get_lighting_preset,
    parse_studio_light_instruction,
)
from app.services.relighting.depth_normal import estimate_depth_and_normals
from app.services.relighting.shadows import build_shadow_params, generate_shadow_layer
from app.services.relighting.softbox import (
    build_softbox_shadow_params,
    softbox_direction,
)
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


def test_softbox_direction_and_opposite_contact_shadow() -> None:
    left_key = StudioLightDTO(
        light_angle=180.0,
        light_elevation=60.0,
        color_temp_k=3200,
        intensity=1.0,
        softbox_diffusion=0.8,
    )
    direction = softbox_direction(left_key)
    assert direction[0] < 0.0  # from the left (−X)
    assert direction[1] > 0.0  # elevated (+Y)

    shadows = build_softbox_shadow_params(left_key)
    assert shadows.contact_strength > 0.0
    # Light from left → contact puddle biased to the right (positive offset).
    assert shadows.contact_offset_ratio > 0.0

    right_key = StudioLightDTO(
        light_angle=0.0,
        light_elevation=45.0,
        color_temp_k=5500,
        intensity=1.2,
        softbox_diffusion=0.3,
    )
    right_shadows = build_softbox_shadow_params(right_key)
    assert right_shadows.contact_offset_ratio < 0.0
    assert right_shadows.blur_px < shadows.blur_px  # harder = less blur


def test_parse_studio_light_instruction_ru_warm_left() -> None:
    light = parse_studio_light_instruction("мягкий тёплый свет слева сверху")
    assert light.light_angle == pytest.approx(180.0)
    assert light.light_elevation >= 60.0
    assert light.color_temp_k == 3200
    assert light.softbox_diffusion >= 0.8


def test_parse_studio_light_instruction_en_hard_cool_right() -> None:
    light = parse_studio_light_instruction("hard cool light from the right")
    assert light.light_angle == pytest.approx(0.0)
    assert light.color_temp_k == 6500
    assert light.softbox_diffusion <= 0.2


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
    assert result.studio_light is None
    assert result.image_png.startswith(b"\x89PNG")
    assert result.width == 96
    assert result.height == 96


@pytest.mark.asyncio
async def test_engine_process_custom_softbox() -> None:
    engine = RelightingEngineService()
    light = StudioLightDTO(
        light_angle=135.0,
        light_elevation=50.0,
        color_temp_k=4000,
        intensity=1.1,
        softbox_diffusion=0.7,
    )
    result = await engine.process_custom(_product_png(), studio_light=light)
    assert result.preset_name is None
    assert result.studio_light == light
    assert result.image_png.startswith(b"\x89PNG")


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
async def test_relighting_service_custom_softbox_billing() -> None:
    user_id = uuid4()
    user = SimpleNamespace(id=user_id, ai_coins=15)

    session = AsyncMock()
    session.commit = AsyncMock()
    billing = MagicMock()
    billing.debit_coins_in_transaction = AsyncMock(return_value=user)
    billing.refund_coins_in_transaction = AsyncMock()
    storage = MagicMock()
    storage.upload_bytes = AsyncMock(
        return_value=S3UploadResult(
            bucket="test-bucket",
            object_key=f"relighting/{user_id}/custom.png",
            etag="xyz",
            presigned_url="https://cdn.example/custom.png",
        )
    )

    light = StudioLightDTO(
        light_angle=180.0,
        light_elevation=65.0,
        color_temp_k=3200,
        intensity=1.0,
        softbox_diffusion=0.85,
    )
    service = RelightingService(session, billing=billing, storage=storage)
    service._download_image = AsyncMock(return_value=_product_png())  # type: ignore[method-assign]

    result = await service.process_custom(
        user_id=user_id,
        image_url="https://cdn.example/product.png",
        studio_light=light,
    )

    assert result.studio_light == light
    assert result.preset_name is None
    assert result.coins_charged == 5
    billing.debit_coins_in_transaction.assert_awaited_once()
    debit_body = billing.debit_coins_in_transaction.await_args.kwargs["response_body"]
    assert debit_body["operation"] == "relighting_custom"


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
