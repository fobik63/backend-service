"""Unit tests for Claude 4.7 Vision & Chain-of-Thought domain/service."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from app.application.claude_reasoning_service import (
    ClaudeReasoningNotFoundError,
    ClaudeReasoningService,
    ClaudeReasoningValidationError,
)
from app.domain.claude_reasoning import (
    ClaudeReasoningJobStatus,
    ClaudeReasoningJobView,
    CompetitorTextContext,
    ReasoningStageResult,
    TextAlignmentItem,
    VisionStageResult,
    VisualTrigger,
    extract_json_object,
    merge_chain_of_thought,
    redis_stage_key,
)

_MIN_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000a49444154789c63000100000500010d0a2db40000000049454e44ae426082"
)


def _vision() -> VisionStageResult:
    return VisionStageResult(
        slide_summary="Яркий первый слайд с болью и оффером",
        color_palette=["#111111", "#FF5500"],
        layout_pattern="product-left, badges-right",
        visual_triggers=[
            VisualTrigger(
                trigger_id="t1",
                category="pain_badge",
                description="Плашка 'не скрипит'",
                location="top-right",
                contrast_role="orange on dark",
                pain_addressed="скрип механизма",
                confidence=0.9,
            ),
            VisualTrigger(
                trigger_id="t2",
                category="offer",
                description="Крупный оффер '2 года гарантии'",
                location="bottom",
                contrast_role="white text",
                pain_addressed="недоверие к качеству",
                confidence=0.8,
            ),
        ],
        blind_spots=["нет размера в руках"],
        reasoning_trace="Сначала заметил контрастную плашку, затем оффер.",
    )


def _reasoning() -> ReasoningStageResult:
    return ReasoningStageResult(
        alignments=[
            TextAlignmentItem(
                trigger_id="t1",
                text_evidence="В описании: бесшумный механизм",
                alignment="confirmed",
                gap_note="Визуал и текст согласованы",
                monetization_signal="Закрывает частую боль из отзывов",
            ),
            TextAlignmentItem(
                trigger_id="t2",
                text_evidence="Гарантия не указана в тексте",
                alignment="contradiction",
                gap_note="На фото обещание без текстового подтверждения",
                monetization_signal="Риск недоверия",
            ),
        ],
        confirmed_triggers=["t1"],
        contradictions=["t2 обещает гарантию без текста"],
        strategic_insights=["Вынести реальную бесшумность на первый слайд"],
        reasoning_trace="Сверил триггеры с описанием и отзывами.",
    )


class _FakeStorage:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    async def upload_bytes(
        self,
        *,
        object_key: str,
        data: bytes,
        content_type: str,
        presign: bool = True,
    ) -> object:
        self.objects[object_key] = data
        return object()

    async def download_bytes(self, *, object_key: str, max_bytes: int) -> bytes:
        data = self.objects[object_key]
        if len(data) > max_bytes:
            raise ValueError("too large")
        return data


class _FakeClaude:
    model_name = "claude-opus-4-7"

    def __init__(self) -> None:
        self.vision_calls = 0
        self.reasoning_calls = 0

    async def analyze_visual_triggers(
        self,
        *,
        images: tuple[tuple[bytes, str], ...],
        product_category: str | None,
    ) -> tuple[VisionStageResult, int, int]:
        self.vision_calls += 1
        assert images
        return _vision(), 100, 50

    async def align_triggers_with_text(
        self,
        *,
        vision: VisionStageResult,
        text_context: CompetitorTextContext,
    ) -> tuple[ReasoningStageResult, int, int]:
        self.reasoning_calls += 1
        assert vision.visual_triggers
        return _reasoning(), 80, 40

    async def aclose(self) -> None:
        return None


class _FakeRepo:
    def __init__(self) -> None:
        self.jobs: dict[UUID, ClaudeReasoningJobView] = {}

    async def create_job(
        self,
        *,
        user_id: UUID,
        image_object_keys: tuple[str, ...],
        text_context: dict,
        model_name: str,
        idempotency_key: str | None = None,
    ) -> ClaudeReasoningJobView:
        now = datetime.now(UTC)
        job = ClaudeReasoningJobView(
            id=uuid4(),
            user_id=user_id,
            status=ClaudeReasoningJobStatus.QUEUED,
            celery_task_id=None,
            image_object_keys=image_object_keys,
            text_context=text_context,
            vision_result=None,
            reasoning_result=None,
            final_result=None,
            model_name=model_name,
            error_message=None,
            input_tokens=0,
            output_tokens=0,
            created_at=now,
            updated_at=now,
            completed_at=None,
        )
        self.jobs[job.id] = job
        return job

    async def find_idempotent_job(
        self, *, user_id: UUID, idempotency_key: str
    ) -> ClaudeReasoningJobView | None:
        for job in self.jobs.values():
            if job.user_id == user_id and job.text_context.get("_idem") == idempotency_key:
                return job
        return None

    async def get_job_for_user(
        self, *, user_id: UUID, job_id: UUID
    ) -> ClaudeReasoningJobView | None:
        job = self.jobs.get(job_id)
        if job is None or job.user_id != user_id:
            return None
        return job

    async def get_job(self, *, job_id: UUID) -> ClaudeReasoningJobView | None:
        return self.jobs.get(job_id)

    async def mark_status(
        self,
        *,
        job_id: UUID,
        status: ClaudeReasoningJobStatus,
        celery_task_id: str | None = None,
        error_message: str | None = None,
        completed_at: datetime | None = None,
    ) -> ClaudeReasoningJobView:
        job = self.jobs[job_id]
        updated = ClaudeReasoningJobView(
            id=job.id,
            user_id=job.user_id,
            status=status,
            celery_task_id=celery_task_id or job.celery_task_id,
            image_object_keys=job.image_object_keys,
            text_context=job.text_context,
            vision_result=job.vision_result,
            reasoning_result=job.reasoning_result,
            final_result=job.final_result,
            model_name=job.model_name,
            error_message=error_message if error_message is not None else job.error_message,
            input_tokens=job.input_tokens,
            output_tokens=job.output_tokens,
            created_at=job.created_at,
            updated_at=datetime.now(UTC),
            completed_at=completed_at or job.completed_at,
        )
        self.jobs[job_id] = updated
        return updated

    async def save_vision_result(
        self,
        *,
        job_id: UUID,
        vision_result: dict,
        input_tokens_delta: int = 0,
        output_tokens_delta: int = 0,
    ) -> ClaudeReasoningJobView:
        job = self.jobs[job_id]
        updated = ClaudeReasoningJobView(
            id=job.id,
            user_id=job.user_id,
            status=ClaudeReasoningJobStatus.REASONING_RUNNING,
            celery_task_id=job.celery_task_id,
            image_object_keys=job.image_object_keys,
            text_context=job.text_context,
            vision_result=vision_result,
            reasoning_result=job.reasoning_result,
            final_result=job.final_result,
            model_name=job.model_name,
            error_message=job.error_message,
            input_tokens=job.input_tokens + input_tokens_delta,
            output_tokens=job.output_tokens + output_tokens_delta,
            created_at=job.created_at,
            updated_at=datetime.now(UTC),
            completed_at=job.completed_at,
        )
        self.jobs[job_id] = updated
        return updated

    async def save_final_result(
        self,
        *,
        job_id: UUID,
        reasoning_result: dict,
        final_result: dict,
        input_tokens_delta: int = 0,
        output_tokens_delta: int = 0,
    ) -> ClaudeReasoningJobView:
        job = self.jobs[job_id]
        updated = ClaudeReasoningJobView(
            id=job.id,
            user_id=job.user_id,
            status=ClaudeReasoningJobStatus.COMPLETED,
            celery_task_id=job.celery_task_id,
            image_object_keys=job.image_object_keys,
            text_context=job.text_context,
            vision_result=job.vision_result,
            reasoning_result=reasoning_result,
            final_result=final_result,
            model_name=job.model_name,
            error_message=None,
            input_tokens=job.input_tokens + input_tokens_delta,
            output_tokens=job.output_tokens + output_tokens_delta,
            created_at=job.created_at,
            updated_at=datetime.now(UTC),
            completed_at=datetime.now(UTC),
        )
        self.jobs[job_id] = updated
        return updated


def _service(
    repo: _FakeRepo | None = None,
    storage: _FakeStorage | None = None,
    claude: _FakeClaude | None = None,
) -> tuple[ClaudeReasoningService, _FakeRepo, _FakeStorage, _FakeClaude]:
    repo = repo or _FakeRepo()
    storage = storage or _FakeStorage()
    claude = claude or _FakeClaude()
    service = ClaudeReasoningService(
        repo,
        storage=storage,
        model_name="claude-opus-4-7",
        max_images=5,
        max_image_bytes=1024 * 1024,
        redis_stage_ttl_seconds=3600,
        claude=claude,
    )
    return service, repo, storage, claude


def test_extract_json_object_from_fenced_markdown() -> None:
    raw = '```json\n{"a": 1, "b": "x"}\n```'
    assert extract_json_object(raw) == {"a": 1, "b": "x"}


def test_merge_chain_of_thought_builds_blueprint() -> None:
    result = merge_chain_of_thought(
        vision=_vision(),
        reasoning=_reasoning(),
        model_name="claude-opus-4-7",
    )
    assert result.model_name == "claude-opus-4-7"
    assert any("pain_badge" in item for item in result.conversion_triggers)
    assert "Стратегические инсайты" in result.actionable_blueprint
    assert 0.0 <= result.confidence_score <= 1.0


def test_redis_stage_key_format() -> None:
    job_id = uuid4()
    assert redis_stage_key(job_id, "vision") == f"claude:reasoning:{job_id}:vision"


@pytest.mark.asyncio
async def test_enqueue_analysis_uploads_and_queues() -> None:
    service, repo, storage, _claude = _service()
    user_id = uuid4()
    job, replay = await service.enqueue_analysis(
        user_id=user_id,
        images=(_MIN_PNG,),
        text_context=CompetitorTextContext(
            title="Кресло офисное",
            product_category="мебель",
            reviews_negative=["скрип"],
        ),
    )
    assert replay is False
    assert job.status == ClaudeReasoningJobStatus.QUEUED
    assert len(job.image_object_keys) == 1
    assert job.image_object_keys[0] in storage.objects
    assert job.id in repo.jobs


@pytest.mark.asyncio
async def test_enqueue_rejects_invalid_image() -> None:
    service, *_ = _service()
    with pytest.raises(ClaudeReasoningValidationError, match="JPEG, PNG, or WebP"):
        await service.enqueue_analysis(
            user_id=uuid4(),
            images=(b"not-an-image",),
            text_context=CompetitorTextContext(),
        )


@pytest.mark.asyncio
async def test_run_chain_of_thought_two_stages(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _no_cache_get(_key: str) -> None:
        return None

    async def _no_cache_set(_key: str, _payload: dict, _ttl: int) -> None:
        return None

    monkeypatch.setattr(
        "app.application.claude_reasoning_service.get_cached_json",
        _no_cache_get,
    )
    monkeypatch.setattr(
        "app.application.claude_reasoning_service.cache_json",
        _no_cache_set,
    )

    service, repo, _storage, claude = _service()
    user_id = uuid4()
    job, _ = await service.enqueue_analysis(
        user_id=user_id,
        images=(_MIN_PNG,),
        text_context=CompetitorTextContext(
            title="Товар",
            description="Бесшумный механизм",
        ),
    )
    completed = await service.run_chain_of_thought(job_id=job.id)
    assert completed.status == ClaudeReasoningJobStatus.COMPLETED
    assert completed.final_result is not None
    assert "conversion_triggers" in completed.final_result
    assert claude.vision_calls == 1
    assert claude.reasoning_calls == 1
    assert completed.input_tokens == 180
    assert completed.output_tokens == 90
    assert repo.jobs[job.id].vision_result is not None


@pytest.mark.asyncio
async def test_get_job_for_user_not_found() -> None:
    service, *_ = _service()
    with pytest.raises(ClaudeReasoningNotFoundError):
        await service.get_job_for_user(user_id=uuid4(), job_id=uuid4())
