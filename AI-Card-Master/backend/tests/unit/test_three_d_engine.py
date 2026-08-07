"""Unit tests for the provider-neutral 3D generation Adapter module."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services.three_d import (
    MOCK_RESULT_URLS,
    BaseThreeDEngine,
    MockThreeDEngineAdapter,
    ThreeDEngineFactory,
    ThreeDGenerationStage,
    ThreeDTaskLifecycleStatus,
)


@pytest.fixture
def mock_engine() -> MockThreeDEngineAdapter:
    return MockThreeDEngineAdapter(
        duration_seconds=0.0,
        queue_delay_seconds=0.0,
        ticks_per_stage=2,
    )


@pytest.mark.asyncio
async def test_mock_create_and_complete_returns_fixture_assets(
    mock_engine: MockThreeDEngineAdapter,
) -> None:
    task_id = await mock_engine.create_generation_task(
        prompt="red sneakers on white pedestal",
        image_url="https://cdn.example/product.png",
        params={},
    )

    assert task_id.startswith("mock-3d-")
    status = await mock_engine.wait_until_settled(task_id, timeout_seconds=5.0)

    assert status.status == ThreeDTaskLifecycleStatus.COMPLETED
    assert status.progress_percent == 100
    assert status.stage is None
    assert status.provider_task_id == task_id
    assert status.result_urls == MOCK_RESULT_URLS
    assert status.result_urls["glb"].endswith(".glb")
    assert status.result_urls["usdz"].endswith(".usdz")
    assert status.result_urls["obj"].endswith(".obj")
    assert "preview" in status.result_urls


@pytest.mark.asyncio
async def test_mock_progresses_through_pipeline_stages() -> None:
    engine = MockThreeDEngineAdapter(
        duration_seconds=0.15,
        queue_delay_seconds=0.0,
        ticks_per_stage=2,
    )
    task_id = await engine.create_generation_task(
        prompt="leather bag",
        image_url=None,
        params={},
    )

    seen_stages: set[ThreeDGenerationStage] = set()
    seen_processing = False
    for _ in range(80):
        status = await engine.get_task_status(task_id)
        if status.status == ThreeDTaskLifecycleStatus.PROCESSING:
            seen_processing = True
            assert 0 <= status.progress_percent <= 100
            if status.stage is not None:
                seen_stages.add(status.stage)
        if status.status in {
            ThreeDTaskLifecycleStatus.COMPLETED,
            ThreeDTaskLifecycleStatus.FAILED,
        }:
            break
        await _brief_yield()

    final = await engine.wait_until_settled(task_id, timeout_seconds=5.0)
    assert final.status == ThreeDTaskLifecycleStatus.COMPLETED
    assert seen_processing
    assert ThreeDGenerationStage.DRAFTING_MESH in seen_stages
    assert ThreeDGenerationStage.GENERATING_TEXTURES in seen_stages
    assert ThreeDGenerationStage.BAKING_MAPS in seen_stages


@pytest.mark.asyncio
async def test_mock_cancel_stops_in_flight_task() -> None:
    engine = MockThreeDEngineAdapter(
        duration_seconds=5.0,
        queue_delay_seconds=0.0,
        ticks_per_stage=10,
    )
    task_id = await engine.create_generation_task(
        prompt="cancel me",
        image_url=None,
        params={},
    )

    await _brief_yield()
    cancelled = await engine.cancel_task(task_id)
    assert cancelled is True

    status = await engine.get_task_status(task_id)
    assert status.status == ThreeDTaskLifecycleStatus.FAILED
    assert status.error_message is not None
    assert "cancel" in status.error_message.lower()

    # Already terminal — second cancel is a no-op.
    assert await engine.cancel_task(task_id) is False


@pytest.mark.asyncio
async def test_mock_simulate_failure_via_params(
    mock_engine: MockThreeDEngineAdapter,
) -> None:
    task_id = await mock_engine.create_generation_task(
        prompt="broken mesh",
        image_url=None,
        params={"simulate_failure": True},
    )
    status = await mock_engine.wait_until_settled(task_id, timeout_seconds=5.0)

    assert status.status == ThreeDTaskLifecycleStatus.FAILED
    assert status.result_urls == {}
    assert status.error_message is not None


@pytest.mark.asyncio
async def test_mock_unknown_task_returns_failed() -> None:
    engine = MockThreeDEngineAdapter(duration_seconds=0.0, queue_delay_seconds=0.0)
    status = await engine.get_task_status("missing-id")

    assert status.status == ThreeDTaskLifecycleStatus.FAILED
    assert status.progress_percent == 0
    assert "Unknown" in (status.error_message or "")


@pytest.mark.asyncio
async def test_mock_rejects_empty_prompt(
    mock_engine: MockThreeDEngineAdapter,
) -> None:
    with pytest.raises(ValueError, match="prompt"):
        await mock_engine.create_generation_task("   ", None, {})


def test_factory_returns_mock_adapter_by_default() -> None:
    settings = SimpleNamespace(
        three_d_provider="mock",
        three_d_mock_duration_seconds=0.0,
        three_d_mock_queue_delay_seconds=0.0,
        three_d_mock_ticks_per_stage=2,
    )
    engine = ThreeDEngineFactory.create(settings)  # type: ignore[arg-type]

    assert isinstance(engine, MockThreeDEngineAdapter)
    assert isinstance(engine, BaseThreeDEngine)


def test_factory_reserved_providers_raise_not_implemented() -> None:
    for provider in ("meshy", "tripo", "runpod"):
        settings = SimpleNamespace(
            three_d_provider=provider,
            three_d_mock_duration_seconds=0.0,
            three_d_mock_queue_delay_seconds=0.0,
            three_d_mock_ticks_per_stage=2,
        )
        with pytest.raises(NotImplementedError, match=provider):
            ThreeDEngineFactory.create(settings)  # type: ignore[arg-type]


def test_factory_rejects_unknown_provider() -> None:
    settings = SimpleNamespace(
        three_d_provider="unknown-vendor",
        three_d_mock_duration_seconds=0.0,
        three_d_mock_queue_delay_seconds=0.0,
        three_d_mock_ticks_per_stage=2,
    )
    with pytest.raises(ValueError, match="Unsupported THREE_D_PROVIDER"):
        ThreeDEngineFactory.create(settings)  # type: ignore[arg-type]


async def _brief_yield() -> None:
    import asyncio

    await asyncio.sleep(0.01)
