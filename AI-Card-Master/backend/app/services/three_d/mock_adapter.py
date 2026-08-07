"""In-memory mock adapter for local development and unit tests."""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from typing import Any

from app.services.three_d.base import BaseThreeDEngine
from app.services.three_d.dto import (
    ThreeDGenerationStage,
    ThreeDTaskLifecycleStatus,
    ThreeDTaskStatusDTO,
)
from app.services.three_d.fixtures import MOCK_RESULT_URLS

logger = logging.getLogger(__name__)

# (stage, progress_at_stage_start, progress_at_stage_end)
_PIPELINE_STAGES: tuple[tuple[ThreeDGenerationStage, int, int], ...] = (
    (ThreeDGenerationStage.DRAFTING_MESH, 0, 33),
    (ThreeDGenerationStage.GENERATING_TEXTURES, 33, 66),
    (ThreeDGenerationStage.BAKING_MAPS, 66, 100),
)


@dataclass
class _MockTaskState:
    """Mutable in-memory record for one mock generation."""

    provider_task_id: str
    prompt: str
    image_url: str | None
    params: dict[str, Any]
    status: ThreeDTaskLifecycleStatus = ThreeDTaskLifecycleStatus.QUEUED
    progress_percent: int = 0
    stage: ThreeDGenerationStage | None = None
    result_urls: dict[str, str] = field(default_factory=dict)
    error_message: str | None = None
    cancelled: bool = False
    runner: asyncio.Task[None] | None = None


class MockThreeDEngineAdapter(BaseThreeDEngine):
    """Fake 3D engine that emulates GPU/API latency via ``asyncio.sleep``.

    Progress advances through ``drafting_mesh`` → ``generating_textures`` →
    ``baking_maps``, then returns prepared ``.glb`` / ``.usdz`` / ``.obj``
    and preview fixture URLs. Intended for local development and auto-tests
    without a real Meshy / Tripo3D / RunPod backend.
    """

    def __init__(
        self,
        *,
        duration_seconds: float = 2.0,
        queue_delay_seconds: float = 0.05,
        result_urls: dict[str, str] | None = None,
        ticks_per_stage: int = 3,
    ) -> None:
        if duration_seconds < 0:
            raise ValueError("duration_seconds must be >= 0.")
        if queue_delay_seconds < 0:
            raise ValueError("queue_delay_seconds must be >= 0.")
        if ticks_per_stage < 1:
            raise ValueError("ticks_per_stage must be >= 1.")

        self._duration_seconds = duration_seconds
        self._queue_delay_seconds = queue_delay_seconds
        self._result_urls = dict(result_urls or MOCK_RESULT_URLS)
        self._ticks_per_stage = ticks_per_stage
        self._tasks: dict[str, _MockTaskState] = {}
        self._lock = asyncio.Lock()

    @property
    def known_task_ids(self) -> frozenset[str]:
        """Task ids currently tracked in this process (tests / diagnostics)."""

        return frozenset(self._tasks)

    async def create_generation_task(
        self,
        prompt: str,
        image_url: str | None,
        params: dict[str, Any],
    ) -> str:
        normalized_prompt = prompt.strip()
        if not normalized_prompt:
            raise ValueError("prompt must be a non-empty string.")

        provider_task_id = f"mock-3d-{uuid.uuid4().hex}"
        duration = self._resolve_duration(params)
        should_fail = bool(params.get("simulate_failure", False))
        fail_at_percent = int(params.get("fail_at_percent", 50))

        state = _MockTaskState(
            provider_task_id=provider_task_id,
            prompt=normalized_prompt,
            image_url=image_url,
            params=dict(params),
        )

        async with self._lock:
            self._tasks[provider_task_id] = state
            state.runner = asyncio.create_task(
                self._simulate_pipeline(
                    provider_task_id,
                    duration_seconds=duration,
                    simulate_failure=should_fail,
                    fail_at_percent=fail_at_percent,
                ),
                name=f"mock-3d-pipeline:{provider_task_id}",
            )

        logger.debug(
            "Mock 3D task created id=%s duration=%.3fs fail=%s",
            provider_task_id,
            duration,
            should_fail,
        )
        return provider_task_id

    async def get_task_status(self, provider_task_id: str) -> ThreeDTaskStatusDTO:
        async with self._lock:
            state = self._tasks.get(provider_task_id)
            if state is None:
                return ThreeDTaskStatusDTO(
                    status=ThreeDTaskLifecycleStatus.FAILED,
                    progress_percent=0,
                    result_urls={},
                    error_message=f"Unknown provider_task_id: {provider_task_id}",
                    provider_task_id=provider_task_id,
                )
            return self._to_dto(state)

    async def cancel_task(self, provider_task_id: str) -> bool:
        async with self._lock:
            state = self._tasks.get(provider_task_id)
            if state is None:
                return False
            if state.status in {
                ThreeDTaskLifecycleStatus.COMPLETED,
                ThreeDTaskLifecycleStatus.FAILED,
            }:
                return False
            state.cancelled = True
            state.status = ThreeDTaskLifecycleStatus.FAILED
            state.error_message = "Cancelled by client."
            state.stage = None
            runner = state.runner

        if runner is not None and not runner.done():
            runner.cancel()
            try:
                await runner
            except asyncio.CancelledError:
                pass
        return True

    async def wait_until_settled(
        self,
        provider_task_id: str,
        *,
        timeout_seconds: float = 30.0,
    ) -> ThreeDTaskStatusDTO:
        """Await the in-process simulator (useful in unit tests)."""

        async with self._lock:
            state = self._tasks.get(provider_task_id)
            runner = state.runner if state is not None else None

        if runner is not None:
            try:
                await asyncio.wait_for(asyncio.shield(runner), timeout=timeout_seconds)
            except asyncio.TimeoutError as exc:
                raise TimeoutError(
                    f"Mock 3D task {provider_task_id} did not settle "
                    f"within {timeout_seconds:.1f}s."
                ) from exc
            except asyncio.CancelledError:
                pass

        return await self.get_task_status(provider_task_id)

    def _resolve_duration(self, params: dict[str, Any]) -> float:
        if "duration_seconds" in params:
            raw = float(params["duration_seconds"])
            if raw < 0:
                raise ValueError("params['duration_seconds'] must be >= 0.")
            return raw
        return self._duration_seconds

    async def _simulate_pipeline(
        self,
        provider_task_id: str,
        *,
        duration_seconds: float,
        simulate_failure: bool,
        fail_at_percent: int,
    ) -> None:
        try:
            if self._queue_delay_seconds > 0:
                await asyncio.sleep(self._queue_delay_seconds)

            if await self._is_cancelled(provider_task_id):
                return

            await self._set_state(
                provider_task_id,
                status=ThreeDTaskLifecycleStatus.PROCESSING,
                progress_percent=0,
                stage=ThreeDGenerationStage.DRAFTING_MESH,
            )

            if duration_seconds <= 0:
                if simulate_failure:
                    await self._fail(provider_task_id, "Simulated provider failure.")
                    return
                await self._complete(provider_task_id)
                return

            stage_budget = duration_seconds / len(_PIPELINE_STAGES)
            tick_sleep = stage_budget / self._ticks_per_stage

            for stage, start_pct, end_pct in _PIPELINE_STAGES:
                if await self._is_cancelled(provider_task_id):
                    return

                await self._set_state(
                    provider_task_id,
                    status=ThreeDTaskLifecycleStatus.PROCESSING,
                    progress_percent=start_pct,
                    stage=stage,
                )

                for tick in range(1, self._ticks_per_stage + 1):
                    if await self._is_cancelled(provider_task_id):
                        return

                    ratio = tick / self._ticks_per_stage
                    progress = int(start_pct + (end_pct - start_pct) * ratio)
                    await self._set_state(
                        provider_task_id,
                        status=ThreeDTaskLifecycleStatus.PROCESSING,
                        progress_percent=progress,
                        stage=stage,
                    )

                    if simulate_failure and progress >= fail_at_percent:
                        await self._fail(
                            provider_task_id,
                            f"Simulated provider failure at {progress}%.",
                        )
                        return

                    if tick_sleep > 0:
                        await asyncio.sleep(tick_sleep)

            if await self._is_cancelled(provider_task_id):
                return
            await self._complete(provider_task_id)
        except asyncio.CancelledError:
            async with self._lock:
                state = self._tasks.get(provider_task_id)
                if state is not None and state.cancelled:
                    state.status = ThreeDTaskLifecycleStatus.FAILED
                    state.error_message = state.error_message or "Cancelled by client."
            raise
        except Exception as exc:  # noqa: BLE001 — mock must never crash the process
            logger.exception("Mock 3D pipeline crashed for %s", provider_task_id)
            await self._fail(provider_task_id, f"Mock pipeline error: {exc}")

    async def _is_cancelled(self, provider_task_id: str) -> bool:
        async with self._lock:
            state = self._tasks.get(provider_task_id)
            return state is None or state.cancelled

    async def _set_state(
        self,
        provider_task_id: str,
        *,
        status: ThreeDTaskLifecycleStatus,
        progress_percent: int,
        stage: ThreeDGenerationStage | None,
    ) -> None:
        async with self._lock:
            state = self._tasks.get(provider_task_id)
            if state is None or state.cancelled:
                return
            state.status = status
            state.progress_percent = progress_percent
            state.stage = stage

    async def _complete(self, provider_task_id: str) -> None:
        async with self._lock:
            state = self._tasks.get(provider_task_id)
            if state is None or state.cancelled:
                return
            state.status = ThreeDTaskLifecycleStatus.COMPLETED
            state.progress_percent = 100
            state.stage = None
            state.result_urls = dict(self._result_urls)
            state.error_message = None

    async def _fail(self, provider_task_id: str, message: str) -> None:
        async with self._lock:
            state = self._tasks.get(provider_task_id)
            if state is None or state.cancelled:
                return
            state.status = ThreeDTaskLifecycleStatus.FAILED
            state.stage = None
            state.error_message = message
            state.result_urls = {}

    @staticmethod
    def _to_dto(state: _MockTaskState) -> ThreeDTaskStatusDTO:
        return ThreeDTaskStatusDTO(
            status=state.status,
            progress_percent=state.progress_percent,
            result_urls=dict(state.result_urls),
            stage=state.stage,
            error_message=state.error_message,
            provider_task_id=state.provider_task_id,
            metadata={
                "prompt": state.prompt,
                "image_url": state.image_url,
                "engine": "mock",
            },
        )
