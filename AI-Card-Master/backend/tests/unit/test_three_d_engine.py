"""Unit tests for the provider-neutral 3D generation Adapter module."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services.three_d import (
    MOCK_RESULT_URLS,
    BaseThreeDEngine,
    MeshyEngineAdapter,
    MockThreeDEngineAdapter,
    ThreeDEngineFactory,
    ThreeDGenerationStage,
    ThreeDTaskLifecycleStatus,
    Tripo3DEngineAdapter,
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


def test_factory_meshy_and_tripo_fall_back_to_mock_without_api_key(
    caplog: pytest.LogCaptureFixture,
) -> None:
    for provider in ("meshy", "tripo", "tripo3d"):
        caplog.clear()
        settings = SimpleNamespace(
            three_d_provider=provider,
            meshy_api_key=None,
            tripo3d_api_key=None,
            three_d_mock_duration_seconds=0.0,
            three_d_mock_queue_delay_seconds=0.0,
            three_d_mock_ticks_per_stage=2,
        )
        with caplog.at_level("WARNING"):
            engine = ThreeDEngineFactory.create(settings, circuit_breaker=None)  # type: ignore[arg-type]
        assert isinstance(engine, MockThreeDEngineAdapter)
        assert "falling back to MockThreeDEngineAdapter" in caplog.text


def test_factory_meshy_returns_adapter_when_api_key_set() -> None:
    settings = SimpleNamespace(
        three_d_provider="meshy",
        meshy_api_key="meshy-test-key",
        meshy_base_url="https://api.meshy.ai/v2",
        meshy_timeout_seconds=30.0,
        tripo3d_api_key=None,
        three_d_mock_duration_seconds=0.0,
        three_d_mock_queue_delay_seconds=0.0,
        three_d_mock_ticks_per_stage=2,
    )
    engine = ThreeDEngineFactory.create(settings, circuit_breaker=None)  # type: ignore[arg-type]
    assert isinstance(engine, MeshyEngineAdapter)


def test_factory_tripo3d_returns_adapter_when_api_key_set() -> None:
    settings = SimpleNamespace(
        three_d_provider="tripo3d",
        tripo3d_api_key="tripo-test-key",
        tripo3d_base_url="https://api.tripo3d.ai/v2/openapi",
        tripo3d_timeout_seconds=30.0,
        meshy_api_key=None,
        three_d_mock_duration_seconds=0.0,
        three_d_mock_queue_delay_seconds=0.0,
        three_d_mock_ticks_per_stage=2,
    )
    engine = ThreeDEngineFactory.create(settings, circuit_breaker=None)  # type: ignore[arg-type]
    assert isinstance(engine, Tripo3DEngineAdapter)


def test_factory_wires_failover_when_both_provider_keys_set() -> None:
    from app.services.three_d import FailoverThreeDEngine

    settings = SimpleNamespace(
        three_d_provider="meshy",
        meshy_api_key="meshy-test-key",
        meshy_base_url="https://api.meshy.ai/v2",
        meshy_timeout_seconds=30.0,
        tripo3d_api_key="tripo-test-key",
        tripo3d_base_url="https://api.tripo3d.ai/v2/openapi",
        tripo3d_timeout_seconds=30.0,
        three_d_mock_duration_seconds=0.0,
        three_d_mock_queue_delay_seconds=0.0,
        three_d_mock_ticks_per_stage=2,
    )
    engine = ThreeDEngineFactory.create(settings, circuit_breaker=None)  # type: ignore[arg-type]
    assert isinstance(engine, FailoverThreeDEngine)

def test_factory_runpod_still_not_implemented() -> None:
    settings = SimpleNamespace(
        three_d_provider="runpod",
        three_d_mock_duration_seconds=0.0,
        three_d_mock_queue_delay_seconds=0.0,
        three_d_mock_ticks_per_stage=2,
    )
    with pytest.raises(NotImplementedError, match="runpod"):
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


@pytest.mark.asyncio
async def test_meshy_adapter_create_and_status_mapping() -> None:
    """Meshy create + status mapping via httpx mock transport."""

    import httpx

    _MESHY_POLL_STATE["status"] = "PENDING"
    _MESHY_POLL_STATE["progress"] = 0
    transport = httpx.MockTransport(_meshy_handler)
    async with httpx.AsyncClient(transport=transport) as client:
        engine = MeshyEngineAdapter(
            api_key="test-key",
            base_url="https://api.meshy.ai/v2",
            client=client,
        )
        task_id = await engine.create_generation_task(
            prompt="a red sneaker",
            image_url=None,
            params={},
        )
        assert task_id == "meshy-task-1"

        queued = await engine.get_task_status(task_id)
        assert queued.status == ThreeDTaskLifecycleStatus.QUEUED

        _MESHY_POLL_STATE["status"] = "IN_PROGRESS"
        _MESHY_POLL_STATE["progress"] = 40
        processing = await engine.get_task_status(task_id)
        assert processing.status == ThreeDTaskLifecycleStatus.PROCESSING
        assert processing.stage == ThreeDGenerationStage.GENERATING_TEXTURES

        _MESHY_POLL_STATE["status"] = "SUCCEEDED"
        _MESHY_POLL_STATE["progress"] = 100
        done = await engine.get_task_status(task_id)
        assert done.status == ThreeDTaskLifecycleStatus.COMPLETED
        assert done.result_urls["glb"].endswith(".glb")
        assert done.progress_percent == 100


@pytest.mark.asyncio
async def test_tripo3d_adapter_create_and_status_mapping() -> None:
    import httpx

    _TRIPO_POLL_STATE["status"] = "queued"
    _TRIPO_POLL_STATE["progress"] = 0
    transport = httpx.MockTransport(_tripo_handler)
    async with httpx.AsyncClient(transport=transport) as client:
        engine = Tripo3DEngineAdapter(
            api_key="test-key",
            base_url="https://api.tripo3d.ai/v2/openapi",
            client=client,
        )
        task_id = await engine.create_generation_task(
            prompt="a wooden chair",
            image_url=None,
            params={},
        )
        assert task_id == "tripo-task-1"

        queued = await engine.get_task_status(task_id)
        assert queued.status == ThreeDTaskLifecycleStatus.QUEUED

        _TRIPO_POLL_STATE["status"] = "running"
        _TRIPO_POLL_STATE["progress"] = 55
        running = await engine.get_task_status(task_id)
        assert running.status == ThreeDTaskLifecycleStatus.PROCESSING

        _TRIPO_POLL_STATE["status"] = "success"
        _TRIPO_POLL_STATE["progress"] = 100
        done = await engine.get_task_status(task_id)
        assert done.status == ThreeDTaskLifecycleStatus.COMPLETED
        assert "glb" in done.result_urls
        assert "preview" in done.result_urls


_MESHY_POLL_STATE: dict[str, object] = {"status": "PENDING", "progress": 0}
_TRIPO_POLL_STATE: dict[str, object] = {"status": "queued", "progress": 0}


def _meshy_handler(request: object) -> object:
    import httpx

    assert isinstance(request, httpx.Request)
    if request.method == "POST" and request.url.path.endswith("/text-to-3d"):
        return httpx.Response(202, json={"result": "meshy-task-1"})
    if request.method == "GET" and "/text-to-3d/" in request.url.path:
        status = str(_MESHY_POLL_STATE["status"])
        progress = int(_MESHY_POLL_STATE["progress"])  # type: ignore[arg-type]
        body: dict[str, object] = {
            "id": "meshy-task-1",
            "status": status,
            "progress": progress,
            "task_error": {"message": ""},
        }
        if status == "SUCCEEDED":
            body["model_urls"] = {
                "glb": "https://assets.meshy.ai/out/model.glb",
                "usdz": "https://assets.meshy.ai/out/model.usdz",
            }
            body["thumbnail_url"] = "https://assets.meshy.ai/out/preview.png"
        return httpx.Response(200, json=body)
    return httpx.Response(404, json={"message": f"unhandled {request.method} {request.url}"})


def _tripo_handler(request: object) -> object:
    import httpx

    assert isinstance(request, httpx.Request)
    if request.method == "POST" and request.url.path.endswith("/task"):
        return httpx.Response(200, json={"code": 0, "data": {"task_id": "tripo-task-1"}})
    if request.method == "GET" and "/task/" in request.url.path:
        status = str(_TRIPO_POLL_STATE["status"])
        progress = int(_TRIPO_POLL_STATE["progress"])  # type: ignore[arg-type]
        data: dict[str, object] = {
            "task_id": "tripo-task-1",
            "type": "text_to_model",
            "status": status,
            "progress": progress,
            "output": {},
        }
        if status == "success":
            data["output"] = {
                "model_url": "https://cdn.tripo3d.ai/output/model.glb",
                "rendered_image_url": "https://cdn.tripo3d.ai/output/preview.png",
            }
        return httpx.Response(200, json={"code": 0, "data": data})
    return httpx.Response(404, json={"code": 2001, "message": "not found"})


async def _brief_yield() -> None:
    import asyncio

    await asyncio.sleep(0.01)


@pytest.mark.asyncio
async def test_meshy_circuit_opens_after_three_429_then_503(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import fakeredis
    import httpx

    from app.domain.circuit_breaker import CIRCUIT_MESHY, CircuitBreakerConfig, CircuitState
    from app.infrastructure import redis as redis_module
    from app.infrastructure.circuit_breaker import RedisCircuitBreaker
    from app.services.three_d.errors import ThreeDServiceUnavailableError

    fake = fakeredis.FakeAsyncRedis(decode_responses=True)
    monkeypatch.setattr(redis_module, "_redis_client", fake)
    breaker = RedisCircuitBreaker(
        CircuitBreakerConfig(failure_threshold=3, failure_window_seconds=60)
    )

    def handler(request: object) -> object:
        assert isinstance(request, httpx.Request)
        return httpx.Response(429, json={"message": "rate limited"})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        engine = MeshyEngineAdapter(
            api_key="test-key",
            base_url="https://api.meshy.ai/v2",
            client=client,
            circuit_breaker=breaker,
        )
        for _ in range(3):
            with pytest.raises(Exception, match="HTTP 429"):
                await engine.create_generation_task("x", None, {})

        assert await breaker.state(CIRCUIT_MESHY) is CircuitState.OPEN
        with pytest.raises(ThreeDServiceUnavailableError, match="temporarily unavailable"):
            await engine.create_generation_task("x", None, {})
        with pytest.raises(ThreeDServiceUnavailableError):
            await engine.ensure_available()
    await fake.aclose()


@pytest.mark.asyncio
async def test_failover_switches_to_tripo_when_meshy_circuit_open(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import fakeredis
    import httpx

    from app.domain.circuit_breaker import CIRCUIT_MESHY, CircuitBreakerConfig
    from app.infrastructure import redis as redis_module
    from app.infrastructure.circuit_breaker import RedisCircuitBreaker
    from app.services.three_d import FailoverThreeDEngine

    fake = fakeredis.FakeAsyncRedis(decode_responses=True)
    monkeypatch.setattr(redis_module, "_redis_client", fake)
    breaker = RedisCircuitBreaker(
        CircuitBreakerConfig(failure_threshold=1, failure_window_seconds=60)
    )

    # Force meshy circuit open.
    await breaker.record_failure(CIRCUIT_MESHY)

    def handler(request: object) -> object:
        assert isinstance(request, httpx.Request)
        if "tripo3d" in str(request.url.host) or request.url.path.endswith("/task"):
            if request.method == "POST":
                return httpx.Response(
                    200, json={"code": 0, "data": {"task_id": "tripo-fb-1"}}
                )
        return httpx.Response(503, json={"message": "meshy down"})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        primary = MeshyEngineAdapter(
            api_key="m",
            base_url="https://api.meshy.ai/v2",
            client=client,
            circuit_breaker=breaker,
        )
        secondary = Tripo3DEngineAdapter(
            api_key="t",
            base_url="https://api.tripo3d.ai/v2/openapi",
            client=client,
            circuit_breaker=breaker,
        )
        engine = FailoverThreeDEngine(
            primary, secondary, primary_name="meshy", fallback_name="tripo3d"
        )
        task_id = await engine.create_generation_task("chair", None, {})
        assert task_id.startswith("f:")
        assert "tripo-fb-1" in task_id
        await engine.aclose()
    await fake.aclose()


@pytest.mark.asyncio
async def test_close_three_d_engine_clears_process_cache() -> None:
    from app.services.three_d.factory import close_three_d_engine, get_three_d_engine

    get_three_d_engine.cache_clear()
    engine = get_three_d_engine()
    assert isinstance(engine, MockThreeDEngineAdapter)
    await close_three_d_engine()
    assert get_three_d_engine.cache_info().currsize == 0
