"""Unit tests for competitor negative-review pain analysis (plan §71)."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from app.application.pain_analysis_service import (
    PainAnalysisNotFoundError,
    PainAnalysisService,
    PainAnalysisValidationError,
)
from app.domain.pain_analysis import (
    PainAnalysisJobStatus,
    PainAnalysisJobView,
    PainAnalysisRequest,
    PainAnalysisResult,
    build_pain_analysis_prompt,
    filter_and_preview_pains,
    normalize_claude_pain_result,
    pain_analysis_system_prompt,
)


def _request(**kwargs) -> PainAnalysisRequest:
    base = {
        "product_name": "Офисное кресло Ergopro",
        "product_specs": "Металлокаркас, нагрузка 150 кг, сетчатая спинка",
        "platform": "wildberries",
        "raw_negative_reviews": [
            "Хлипкий пластик ножек, скрипит через неделю",
            "Не разобрался как включать газлифт",
            "Долго шло, порвали коробку при транспортировке",
            "Ужасно",
            "Маломерит сиденье, для крупного человека тесно",
            "Пахнет дешёвой резиной первую неделю",
            "Верните деньги",
            "Перепутали цвет на складе WB",
        ],
    }
    base.update(kwargs)
    return PainAnalysisRequest.model_validate(base)


def test_platform_aliases() -> None:
    assert _request(platform="WB").platform == "wildberries"
    assert _request(platform="Озон").platform == "ozon"


def test_platform_rejects_unknown() -> None:
    with pytest.raises(ValidationError):
        _request(platform="amazon")


def test_deterministic_filter_drops_junk_and_keeps_real_pains() -> None:
    result = filter_and_preview_pains(_request())
    junk_blob = " ".join(result.filtered_out_junk).casefold()
    assert "инструкц" in junk_blob or "пользовател" in junk_blob
    assert "доставк" in junk_blob or "транспорт" in junk_blob
    assert "эмоциональн" in junk_blob

    pains_blob = " ".join(result.real_product_pains).casefold()
    assert "хлипк" in pains_blob or "скрип" in pains_blob
    assert "маломер" in pains_blob or "сидень" in pains_blob
    assert "пахнет" in pains_blob or "резин" in pains_blob
    assert len(result.infographic_badges) == 4
    assert result.seo_title
    assert result.seo_description
    assert result.insufficient_data is False
    assert result.model_name == "deterministic"


def test_insufficient_data_when_only_junk() -> None:
    result = filter_and_preview_pains(
        _request(
            raw_negative_reviews=[
                "Ужасно",
                "Долго шло",
                "Не прочитал инструкцию",
                "Верните деньги",
            ]
        )
    )
    assert result.insufficient_data is True
    assert len(result.infographic_badges) == 4


def test_prompt_contains_reviews_and_filter_rules() -> None:
    prompt = build_pain_analysis_prompt(request=_request())
    assert "Хлипкий пластик" in prompt
    assert "ИГНОРИРОВАТЬ" in prompt
    assert "Wildberries" in prompt
    assert "seo_title" in prompt
    assert pain_analysis_system_prompt().startswith("Ты — профессиональный")


def test_normalize_claude_result() -> None:
    result = normalize_claude_pain_result(
        {
            "filtered_out_junk": ["Ужасно — эмоциональный шум"],
            "real_product_pains": ["Хлипкие ножки", "Запах резины", "Маломерит"],
            "infographic_badges": [
                "Усиленный каркас",
                "Без запаха",
                "Точный размер",
                "Надёжная упаковка",
            ],
            "seo_title": "Кресло без хлипких ножек",
            "seo_description": "Продающий текст закрывает боли.",
        },
        model_name="claude-test",
    )
    assert result.model_name == "claude-test"
    assert len(result.real_product_pains) == 3
    assert len(result.infographic_badges) == 4


def test_normalize_rejects_wrong_badge_count() -> None:
    with pytest.raises(ValueError, match="4 infographic_badges"):
        normalize_claude_pain_result(
            {
                "filtered_out_junk": [],
                "real_product_pains": ["боль"],
                "infographic_badges": ["a", "b", "c"],
                "seo_title": "t",
                "seo_description": "d",
            },
            model_name="m",
        )


class _FakeRepo:
    def __init__(self) -> None:
        self.jobs: dict[UUID, PainAnalysisJobView] = {}

    async def create_job(self, **kwargs) -> PainAnalysisJobView:
        job_id = uuid4()
        now = datetime.now(UTC)
        view = PainAnalysisJobView(
            id=job_id,
            user_id=kwargs["user_id"],
            status=PainAnalysisJobStatus.QUEUED,
            celery_task_id=None,
            product_name=kwargs["product_name"],
            platform=kwargs["platform"],
            request_payload=kwargs["request_payload"],
            filter_preview=None,
            analysis_result=None,
            model_name=kwargs["model_name"],
            error_message=None,
            input_tokens=0,
            output_tokens=0,
            created_at=now,
            updated_at=now,
            completed_at=None,
        )
        self.jobs[job_id] = view
        return view

    async def find_idempotent_job(self, *, user_id, idempotency_key):
        for job in self.jobs.values():
            if job.user_id == user_id:
                return job
        return None

    async def get_job_for_user(self, *, user_id, job_id):
        job = self.jobs.get(job_id)
        if job is None or job.user_id != user_id:
            return None
        return job

    async def get_job(self, *, job_id):
        return self.jobs.get(job_id)

    async def mark_status(self, *, job_id, status, celery_task_id=None, error_message=None, completed_at=None):
        job = self.jobs[job_id]
        self.jobs[job_id] = PainAnalysisJobView(
            id=job.id,
            user_id=job.user_id,
            status=status,
            celery_task_id=celery_task_id if celery_task_id is not None else job.celery_task_id,
            product_name=job.product_name,
            platform=job.platform,
            request_payload=job.request_payload,
            filter_preview=job.filter_preview,
            analysis_result=job.analysis_result,
            model_name=job.model_name,
            error_message=error_message if error_message is not None else job.error_message,
            input_tokens=job.input_tokens,
            output_tokens=job.output_tokens,
            created_at=job.created_at,
            updated_at=datetime.now(UTC),
            completed_at=completed_at if completed_at is not None else job.completed_at,
        )
        return self.jobs[job_id]

    async def save_filter_preview(self, *, job_id, filter_preview):
        job = self.jobs[job_id]
        self.jobs[job_id] = PainAnalysisJobView(
            id=job.id,
            user_id=job.user_id,
            status=job.status,
            celery_task_id=job.celery_task_id,
            product_name=job.product_name,
            platform=job.platform,
            request_payload=job.request_payload,
            filter_preview=filter_preview,
            analysis_result=job.analysis_result,
            model_name=job.model_name,
            error_message=job.error_message,
            input_tokens=job.input_tokens,
            output_tokens=job.output_tokens,
            created_at=job.created_at,
            updated_at=datetime.now(UTC),
            completed_at=job.completed_at,
        )
        return self.jobs[job_id]

    async def save_final_result(
        self, *, job_id, analysis_result, input_tokens_delta=0, output_tokens_delta=0
    ):
        job = self.jobs[job_id]
        self.jobs[job_id] = PainAnalysisJobView(
            id=job.id,
            user_id=job.user_id,
            status=PainAnalysisJobStatus.COMPLETED,
            celery_task_id=job.celery_task_id,
            product_name=job.product_name,
            platform=job.platform,
            request_payload=job.request_payload,
            filter_preview=job.filter_preview,
            analysis_result=analysis_result,
            model_name=job.model_name,
            error_message=None,
            input_tokens=job.input_tokens + input_tokens_delta,
            output_tokens=job.output_tokens + output_tokens_delta,
            created_at=job.created_at,
            updated_at=datetime.now(UTC),
            completed_at=datetime.now(UTC),
        )
        return self.jobs[job_id]


class _FakeClaude:
    model_name = "claude-fake"

    async def analyze_competitor_pains(self, *, request, user_id=None, job_id=None):
        result = PainAnalysisResult(
            filtered_out_junk=["Ужасно — эмоциональный шум"],
            real_product_pains=["Хлипкие ножки", "Запах резины"],
            infographic_badges=[
                "Усиленный каркас — без хлипкости",
                "Без резкого запаха",
                "Точная посадка сиденья",
                "Надёжная упаковка",
            ],
            seo_title="Кресло Ergopro без скрипа",
            seo_description="Закрываем боли конкурентов на WB.",
            model_name=self.model_name,
        )
        return result, 11, 22

    async def aclose(self) -> None:
        return None


@pytest.mark.asyncio
async def test_service_preview_and_run_with_claude() -> None:
    repo = _FakeRepo()
    service = PainAnalysisService(
        repo,
        model_name="claude-test",
        redis_stage_ttl_seconds=60,
        analyzer=_FakeClaude(),
    )
    request = _request()
    preview = service.preview_filter(request)
    assert preview.real_product_pains

    user_id = uuid4()
    job, replay = await service.enqueue_analysis(user_id=user_id, request=request)
    assert replay is False
    finished = await service.run_analysis(job_id=job.id)
    assert finished.status == PainAnalysisJobStatus.COMPLETED
    assert finished.analysis_result is not None
    assert finished.analysis_result["seo_title"] == "Кресло Ergopro без скрипа"
    assert finished.input_tokens == 11
    assert finished.output_tokens == 22


@pytest.mark.asyncio
async def test_service_deterministic_when_claude_missing() -> None:
    repo = _FakeRepo()
    service = PainAnalysisService(
        repo,
        model_name="claude-test",
        redis_stage_ttl_seconds=60,
        analyzer=None,
    )
    user_id = uuid4()
    job, _ = await service.enqueue_analysis(user_id=user_id, request=_request())
    finished = await service.run_analysis(job_id=job.id)
    assert finished.status == PainAnalysisJobStatus.COMPLETED
    assert finished.analysis_result is not None
    assert finished.analysis_result["model_name"] == "deterministic"


@pytest.mark.asyncio
async def test_service_not_found() -> None:
    service = PainAnalysisService(
        _FakeRepo(),
        model_name="claude-test",
        redis_stage_ttl_seconds=60,
    )
    with pytest.raises(PainAnalysisNotFoundError):
        await service.get_job_for_user(user_id=uuid4(), job_id=uuid4())


def test_service_rejects_empty_model_name() -> None:
    with pytest.raises(PainAnalysisValidationError):
        PainAnalysisService(_FakeRepo(), model_name=" ", redis_stage_ttl_seconds=60)
