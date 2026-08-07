"""Use cases for competitor-link deep scrape + Claude deep analysis (plan §77–78)."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from app.application.ports.claude_reasoning import ClaudeStageCachePort
from app.application.ports.competitor_audit import (
    CompetitorAuditPersistencePort,
    CompetitorCardImagePort,
    CompetitorDeepAnalysisPort,
    CompetitorDeepAnalysisTriggerPort,
    CompetitorDeepScraperPort,
)
from app.application.zero_hallucination_service import ZeroHallucinationService
from app.domain.competitor_audit import (
    MAX_VISION_IMAGES_PER_CARD,
    CompetitorAuditEnqueueRequest,
    CompetitorAuditJobStatus,
    CompetitorAuditJobView,
    CompetitorAuditPermanentError,
    CompetitorAuditResult,
    CompetitorAuditTransientError,
    CompetitorCardDeepAnalysis,
    CompetitorCardScrapeResult,
    CompetitorDeepAnalysisBundle,
    assemble_deep_analysis_bundle,
    attach_cross_check_to_card,
    build_insufficient_card_analysis,
    card_has_sufficient_analysis_inputs,
    dump_competitor_audit_result,
    dump_deep_analysis_bundle,
    parse_competitor_product_link,
    redis_competitor_audit_key,
)
from app.infrastructure.http_resilience import gather_bounded
from app.infrastructure.stock_parser.exceptions import (
    ParserHttpError,
    ParserSchemaError,
    ParserTransportError,
)

logger = logging.getLogger(__name__)

_SCRAPE_CONCURRENCY = 3
_ANALYSIS_CONCURRENCY = 2



class _NullStageCache:
    async def get(self, key: str) -> dict[str, Any] | None:
        return None

    async def set(self, key: str, payload: dict[str, Any], ttl_seconds: int) -> None:
        return None


class CompetitorAuditError(Exception):
    """Base competitor-audit workflow failure."""


class CompetitorAuditValidationError(CompetitorAuditError):
    """Invalid request payload."""


class CompetitorAuditNotFoundError(CompetitorAuditError):
    """Job was not found for the user."""


class CompetitorAuditService:
    """Coordinate link validation → Celery deep scrape → Claude deep analysis."""

    def __init__(
        self,
        repository: CompetitorAuditPersistencePort,
        *,
        scraper: CompetitorDeepScraperPort,
        redis_raw_ttl_seconds: int,
        analyzer: CompetitorDeepAnalysisPort | None = None,
        images: CompetitorCardImagePort | None = None,
        analysis_trigger: CompetitorDeepAnalysisTriggerPort | None = None,
        model_name: str = "claude-opus-4-7",
        max_vision_images: int = MAX_VISION_IMAGES_PER_CARD,
        stage_cache: ClaudeStageCachePort | None = None,
        cross_check: ZeroHallucinationService | None = None,
    ) -> None:
        if redis_raw_ttl_seconds <= 0:
            raise CompetitorAuditValidationError(
                "redis_raw_ttl_seconds must be positive."
            )
        if max_vision_images < 1:
            raise CompetitorAuditValidationError("max_vision_images must be >= 1.")
        self._repository = repository
        self._scraper = scraper
        self._redis_raw_ttl_seconds = redis_raw_ttl_seconds
        self._analyzer = analyzer
        self._images = images
        self._analysis_trigger = analysis_trigger
        self._model_name = model_name.strip() or "claude-opus-4-7"
        self._max_vision_images = max_vision_images
        self._stage_cache = stage_cache or _NullStageCache()
        self._cross_check = cross_check

    async def enqueue_audit(
        self,
        *,
        user_id: UUID,
        request: CompetitorAuditEnqueueRequest,
        idempotency_key: str | None = None,
    ) -> tuple[CompetitorAuditJobView, bool]:
        """Create a queued job; caller publishes Celery scrape task.

        Returns (job, idempotent_replay).
        """

        try:
            request.parsed_links()
        except ValueError as exc:
            raise CompetitorAuditValidationError(str(exc)) from exc

        if idempotency_key:
            existing = await self._repository.find_idempotent_job(
                user_id=user_id,
                idempotency_key=idempotency_key.strip(),
            )
            if existing is not None:
                return existing, True

        job = await self._repository.create_job(
            user_id=user_id,
            links=list(request.links),
            idempotency_key=idempotency_key.strip() if idempotency_key else None,
        )
        return job, False

    async def attach_celery_task(
        self, *, job_id: UUID, celery_task_id: str
    ) -> CompetitorAuditJobView:
        return await self._repository.mark_status(
            job_id=job_id,
            status=CompetitorAuditJobStatus.QUEUED,
            celery_task_id=celery_task_id,
        )

    async def get_job_for_user(
        self, *, user_id: UUID, job_id: UUID
    ) -> CompetitorAuditJobView:
        job = await self._repository.get_job_for_user(user_id=user_id, job_id=job_id)
        if job is None:
            raise CompetitorAuditNotFoundError("Competitor audit job not found.")
        return job

    async def run_scrape(self, *, job_id: UUID) -> CompetitorAuditJobView:
        """Deep-scrape all job links; cache raw log; enqueue Claude analysis.

        Prompt-efficiency shape (2 DB passes + 1 bounded scrape gather):
        1) claim SCRAPING (hydrated job, no re-get)
        2) save_scrape_result → ANALYZING; enqueue Claude
        Per-link try/except isolation preserved inside the gather worker.
        """

        job = await self._repository.get_job(job_id=job_id)
        if job is None:
            raise CompetitorAuditNotFoundError("Competitor audit job not found.")
        if (
            job.status == CompetitorAuditJobStatus.COMPLETED
            and job.result_payload
            and job.analysis_payload
        ):
            return job
        if job.status == CompetitorAuditJobStatus.ANALYZING and job.result_payload:
            # Scrape already done — ensure analysis is queued / runnable.
            self._enqueue_analysis_if_needed(job_id=job_id)
            return job
        if job.status == CompetitorAuditJobStatus.FAILED:
            raise CompetitorAuditPermanentError(
                job.error_message or "Competitor audit job previously failed."
            )

        try:
            job = await self._repository.mark_status(
                job_id=job_id,
                status=CompetitorAuditJobStatus.SCRAPING,
            )

            scrape_results = await gather_bounded(
                tuple(job.links_payload),
                self._scrape_one_link,
                limit=_SCRAPE_CONCURRENCY,
                return_exceptions=True,
            )

            cards: list[CompetitorCardScrapeResult] = []
            parse_log: list[str] = []
            transient: CompetitorAuditTransientError | None = None
            permanent: CompetitorAuditPermanentError | None = None

            for raw_url, result in zip(
                job.links_payload, scrape_results, strict=True
            ):
                if isinstance(result, CompetitorAuditTransientError):
                    parse_log.append(f"transient_error url={raw_url}: {result}")
                    transient = result
                    continue
                if isinstance(result, CompetitorAuditPermanentError):
                    parse_log.append(f"permanent_error url={raw_url}: {result}")
                    permanent = result
                    continue
                if isinstance(result, BaseException):
                    parse_log.append(f"unexpected_error url={raw_url}: {result}")
                    permanent = CompetitorAuditPermanentError(str(result))
                    continue
                card, link_log = result
                cards.append(card)
                parse_log.extend(link_log)

            if transient is not None:
                await self._write_raw_cache(
                    job_id,
                    {
                        "job_id": str(job_id),
                        "status": "retrying",
                        "parse_log": parse_log,
                        "partial_cards": [
                            c.model_dump(mode="json") for c in cards
                        ],
                    },
                )
                raise transient
            if permanent is not None and not cards:
                raise permanent
            if permanent is not None and cards:
                # Mixed batch: keep successful cards, surface permanent via log.
                parse_log.append(f"partial_permanent: {permanent}")

            result = CompetitorAuditResult(cards=cards, parse_log=parse_log)
            result_payload = dump_competitor_audit_result(result)

            await self._write_raw_cache(
                job_id,
                {
                    "job_id": str(job_id),
                    "status": "scraped",
                    "parse_log": parse_log,
                    "cards": result_payload.get("cards", []),
                    "raw_fragments": [card.raw_fragments for card in cards],
                },
            )

            job = await self._repository.save_scrape_result(
                job_id=job_id,
                result_payload=result_payload,
            )
            self._enqueue_analysis_if_needed(job_id=job_id)
            return job
        except CompetitorAuditTransientError:
            raise
        except CompetitorAuditPermanentError as exc:
            logger.warning(
                "Competitor audit permanent failure job_id=%s: %s", job_id, exc
            )
            await self._repository.mark_status(
                job_id=job_id,
                status=CompetitorAuditJobStatus.FAILED,
                error_message=str(exc)[:1000],
                completed_at=datetime.now(UTC),
            )
            raise
        except CompetitorAuditError:
            raise
        except Exception as exc:
            logger.exception("Competitor audit failed for job_id=%s", job_id)
            await self._repository.mark_status(
                job_id=job_id,
                status=CompetitorAuditJobStatus.FAILED,
                error_message=str(exc)[:1000],
                completed_at=datetime.now(UTC),
            )
            raise CompetitorAuditError(str(exc)) from exc

    async def _scrape_one_link(
        self, raw_url: str
    ) -> tuple[CompetitorCardScrapeResult, list[str]]:
        """Scrape a single link; raise typed errors for the gather aggregator."""

        try:
            link = parse_competitor_product_link(raw_url)
        except ValueError as exc:
            raise CompetitorAuditPermanentError(str(exc)) from exc

        parse_log = [
            f"start marketplace={link.marketplace.value} article={link.article}"
        ]
        try:
            card = await self._scraper.scrape_card(link)
        except (ParserTransportError, ParserHttpError) as exc:
            if _is_transient_parser_error(exc):
                raise CompetitorAuditTransientError(str(exc)) from exc
            raise CompetitorAuditPermanentError(str(exc)) from exc
        except ParserSchemaError as exc:
            raise CompetitorAuditPermanentError(str(exc)) from exc

        parse_log.append(
            f"ok article={link.article} photos={len(card.photo_urls)} "
            f"specs={len(card.specs)} reviews={card.reviews_total_fetched} "
            f"low={len(card.reviews_low)} high={len(card.reviews_high)}"
        )
        if card.scrape_warnings:
            parse_log.extend(
                f"warn article={link.article}: {w}" for w in card.scrape_warnings
            )
        return card, parse_log

    async def run_deep_analysis(self, *, job_id: UUID) -> CompetitorAuditJobView:
        """Claude 4.7 Opus Vision + reviews → frontend JSON (plan §78).

        Prompt-efficiency: claim ANALYZING once, bounded Claude gather, one save.
        """

        job = await self._repository.get_job(job_id=job_id)
        if job is None:
            raise CompetitorAuditNotFoundError("Competitor audit job not found.")
        if job.status == CompetitorAuditJobStatus.COMPLETED and job.analysis_payload:
            return job
        if job.status == CompetitorAuditJobStatus.FAILED:
            raise CompetitorAuditPermanentError(
                job.error_message or "Competitor audit job previously failed."
            )
        if not job.result_payload:
            raise CompetitorAuditPermanentError(
                "Cannot run deep analysis before scrape result is available."
            )

        try:
            job = await self._repository.mark_status(
                job_id=job_id,
                status=CompetitorAuditJobStatus.ANALYZING,
            )

            scrape = CompetitorAuditResult.model_validate(job.result_payload)
            analysis_results = await gather_bounded(
                tuple(scrape.cards),
                lambda card: self._analyze_one_card(
                    card=card,
                    user_id=job.user_id,
                    job_id=job_id,
                ),
                limit=_ANALYSIS_CONCURRENCY,
                return_exceptions=True,
            )

            analyses: list[CompetitorCardDeepAnalysis] = []
            notes: list[str] = []
            total_in = 0
            total_out = 0
            model_used = self._model_name

            for card, result in zip(scrape.cards, analysis_results, strict=True):
                if isinstance(result, BaseException):
                    logger.warning(
                        "Deep analysis failed article=%s: %s",
                        card.article,
                        result,
                        exc_info=result,
                    )
                    analyses.append(
                        build_insufficient_card_analysis(
                            card,
                            reason=f"Analysis failed: {result}"[:400],
                        )
                    )
                    notes.append(f"analysis_error article={card.article}")
                    continue
                card_result, in_tok, out_tok, note = result
                analyses.append(card_result)
                total_in += in_tok
                total_out += out_tok
                if note:
                    notes.append(note)
                if self._analyzer is not None:
                    model_used = self._analyzer.model_name or model_used

            bundle = assemble_deep_analysis_bundle(
                analyses,
                model_name=model_used,
                notes=notes,
            )
            payload = dump_deep_analysis_bundle(bundle)
            await self._write_raw_cache(
                job_id,
                {
                    "job_id": str(job_id),
                    "status": "analyzed",
                    "analysis": payload,
                },
            )
            return await self._repository.save_analysis_result(
                job_id=job_id,
                analysis_payload=payload,
                model_name=model_used,
                input_tokens_delta=total_in,
                output_tokens_delta=total_out,
            )
        except CompetitorAuditPermanentError as exc:
            logger.warning(
                "Competitor deep analysis permanent failure job_id=%s: %s",
                job_id,
                exc,
            )
            await self._repository.mark_status(
                job_id=job_id,
                status=CompetitorAuditJobStatus.FAILED,
                error_message=str(exc)[:1000],
                completed_at=datetime.now(UTC),
            )
            raise
        except CompetitorAuditError:
            raise
        except Exception as exc:
            logger.exception("Competitor deep analysis failed job_id=%s", job_id)
            await self._repository.mark_status(
                job_id=job_id,
                status=CompetitorAuditJobStatus.FAILED,
                error_message=str(exc)[:1000],
                completed_at=datetime.now(UTC),
            )
            raise CompetitorAuditError(str(exc)) from exc

    async def _analyze_one_card(
        self,
        *,
        card: CompetitorCardScrapeResult,
        user_id: UUID,
        job_id: UUID,
    ) -> tuple[CompetitorCardDeepAnalysis, int, int, str | None]:
        if not card_has_sufficient_analysis_inputs(card):
            return (
                build_insufficient_card_analysis(
                    card,
                    reason=(
                        "No photos, reviews, or description available for "
                        "anti-hallucination-safe audit."
                    ),
                ),
                0,
                0,
                f"insufficient_data article={card.article}",
            )

        if self._analyzer is None:
            logger.warning(
                "Claude unavailable for competitor deep analysis job_id=%s "
                "article=%s; returning insufficient_data.",
                job_id,
                card.article,
            )
            return (
                build_insufficient_card_analysis(
                    card,
                    reason=(
                        "Claude 4.7 Opus is not configured; refusing to invent "
                        "weaknesses without model evidence."
                    ),
                ),
                0,
                0,
                f"claude_unavailable article={card.article}",
            )

        images: tuple[tuple[bytes, str], ...] = ()
        if self._images is not None and card.photo_urls:
            fetched = await self._images.fetch_urls(
                urls=list(card.photo_urls),
                max_images=self._max_vision_images,
            )
            images = tuple((blob, mime) for blob, mime, _url in fetched)

        if not images and not card.reviews_low and not card.reviews_high:
            # Description-only is weak; still allow text-only Claude if description.
            if not (card.description or "").strip():
                return (
                    build_insufficient_card_analysis(
                        card,
                        reason="Could not download photos and reviews are empty.",
                    ),
                    0,
                    0,
                    f"no_vision_inputs article={card.article}",
                )

        result, in_tok, out_tok = await self._analyzer.analyze_competitor_card(
            card=card,
            images=images,
            user_id=user_id,
            job_id=job_id,
        )

        cross_in = 0
        cross_out = 0
        if self._cross_check is not None and self._cross_check.enabled and images:
            specs_lines = [f"{row.name}: {row.value}" for row in card.specs]
            cross_result, cross_in, cross_out = await self._cross_check.cross_check_card(
                images=images,
                title=card.title,
                description=card.description,
                specs=specs_lines,
                marketplace=card.marketplace.value,
                article=card.article,
                user_id=user_id,
                job_id=job_id,
            )
            result = attach_cross_check_to_card(result, cross_check=cross_result)
        else:
            result = attach_cross_check_to_card(result, cross_check=None)

        return result, in_tok + cross_in, out_tok + cross_out, None

    def _enqueue_analysis_if_needed(self, *, job_id: UUID) -> None:
        if self._analysis_trigger is None:
            logger.warning(
                "No analysis trigger configured; deep analysis will not auto-start "
                "job_id=%s",
                job_id,
            )
            return
        task_id = self._analysis_trigger.enqueue_deep_analysis(job_id=job_id)
        logger.info(
            "Enqueued competitor deep analysis job_id=%s celery_task_id=%s",
            job_id,
            task_id,
        )

    async def _write_raw_cache(self, job_id: UUID, payload: dict[str, Any]) -> None:
        try:
            await self._stage_cache.set(
                redis_competitor_audit_key(job_id, "raw"),
                payload,
                self._redis_raw_ttl_seconds,
            )
        except Exception:
            logger.warning(
                "Skipped competitor-audit raw cache job_id=%s",
                job_id,
                exc_info=True,
            )

    async def read_raw_cache(self, job_id: UUID) -> dict[str, Any] | None:
        try:
            return await self._stage_cache.get(redis_competitor_audit_key(job_id, "raw"))
        except Exception:
            return None

    async def aclose(self) -> None:
        """Release scraper / analyzer / image HTTP resources."""

        await self._scraper.aclose()
        if self._analyzer is not None:
            await self._analyzer.aclose()
        if self._images is not None:
            await self._images.aclose()
        # cross_check reuses the analyzer Claude client — do not double-close.


class CeleryCompetitorDeepAnalysisTrigger:
    """Adapter: enqueue Claude deep-analysis after scrape completes."""

    def enqueue_deep_analysis(self, *, job_id: UUID) -> str:
        from app.workers.competitor_audit_tasks import run_competitor_deep_analysis_task

        async_result = run_competitor_deep_analysis_task.delay(str(job_id))
        return str(async_result.id)


def _is_transient_parser_error(exc: Exception) -> bool:
    """Timeouts and captcha/rate-limit responses are retryable."""

    if isinstance(exc, ParserTransportError):
        return True
    if isinstance(exc, ParserHttpError):
        return exc.status_code in {403, 429, 502, 503, 504}
    return False
