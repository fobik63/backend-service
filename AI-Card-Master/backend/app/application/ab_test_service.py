"""Use cases for Automated A/B Testing Logic."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from app.application.ports.ab_test import (
    AbCredentialsPort,
    AbHypothesisGenerationPort,
    AbTestPersistencePort,
    MarketplaceAdsPort,
)
from app.domain.ab_test import (
    CANONICAL_STRATEGIES,
    AbEnqueueRequest,
    AbExperimentStatus,
    AbExperimentView,
    AbProductBrief,
    AbTestConfig,
    AbVariantHypothesis,
    AbVariantStatus,
    build_deterministic_hypotheses,
    build_resolution_result,
    dump_hypotheses,
    dump_resolution,
    is_measurement_complete,
    measurement_window_end,
    normalize_hypotheses,
    redis_ab_stage_key,
)
from app.infrastructure.redis import (
    RedisUnavailableError,
    cache_json,
    get_cached_json,
)

logger = logging.getLogger(__name__)


class AbTestError(Exception):
    """Base Automated A/B Testing workflow failure."""


class AbTestValidationError(AbTestError):
    """Invalid request payload."""


class AbTestNotFoundError(AbTestError):
    """Experiment was not found for the user."""


class AbTestCredentialsError(AbTestError):
    """Marketplace ads credentials missing or invalid."""


class AbTestService:
    """Coordinate hypothesis generation → ads publish → CTR poll → keep winner."""

    def __init__(
        self,
        repository: AbTestPersistencePort,
        *,
        model_name: str,
        redis_stage_ttl_seconds: int,
        default_config: AbTestConfig | None = None,
        hypothesis_generator: AbHypothesisGenerationPort | None = None,
        ads_client_factory: Any | None = None,
        credentials: AbCredentialsPort | None = None,
        allow_ads_fallback: bool = True,
    ) -> None:
        if not model_name.strip():
            raise AbTestValidationError("model_name must not be empty.")
        if redis_stage_ttl_seconds <= 0:
            raise AbTestValidationError("redis_stage_ttl_seconds must be positive.")
        self._repository = repository
        self._hypothesis_generator = hypothesis_generator
        self._ads_client_factory = ads_client_factory
        self._credentials = credentials
        self._model_name = model_name.strip()
        self._redis_stage_ttl_seconds = redis_stage_ttl_seconds
        self._default_config = default_config or AbTestConfig()
        self._allow_ads_fallback = allow_ads_fallback

    def preview_hypotheses(
        self, request: AbEnqueueRequest
    ) -> tuple[AbVariantHypothesis, ...]:
        """Synchronous deterministic preview of the three strategies."""

        return build_deterministic_hypotheses(request.product)

    async def enqueue_experiment(
        self,
        *,
        user_id: UUID,
        request: AbEnqueueRequest,
        idempotency_key: str | None = None,
    ) -> tuple[AbExperimentView, bool]:
        """Create a queued A/B experiment with three pending variant slots."""

        if idempotency_key:
            existing = await self._repository.find_idempotent_experiment(
                user_id=user_id,
                idempotency_key=idempotency_key.strip(),
            )
            if existing is not None:
                return existing, True

        config = request.config or self._default_config
        experiment = await self._repository.create_experiment(
            user_id=user_id,
            marketplace=request.product.marketplace,
            niche_key=request.product.niche_key,
            sku=request.product.sku,
            nm_id=request.product.nm_id,
            campaign_id=request.product.campaign_id,
            product_payload=request.product.model_dump(mode="json"),
            config=config.model_dump(mode="json"),
            model_name=self._model_name,
            strategies=CANONICAL_STRATEGIES,
            idempotency_key=idempotency_key.strip() if idempotency_key else None,
        )
        return experiment, False

    async def attach_celery_task(
        self, *, experiment_id: UUID, celery_task_id: str
    ) -> AbExperimentView:
        return await self._repository.mark_status(
            experiment_id=experiment_id,
            status=AbExperimentStatus.QUEUED,
            celery_task_id=celery_task_id,
        )

    async def get_experiment_for_user(
        self, *, user_id: UUID, experiment_id: UUID
    ) -> AbExperimentView:
        experiment = await self._repository.get_experiment_for_user(
            user_id=user_id,
            experiment_id=experiment_id,
        )
        if experiment is None:
            raise AbTestNotFoundError("A/B experiment not found.")
        return experiment

    async def list_experiments_for_user(
        self, *, user_id: UUID, limit: int = 20
    ) -> tuple[AbExperimentView, ...]:
        return await self._repository.list_experiments_for_user(
            user_id=user_id,
            limit=limit,
        )

    async def run_generate_and_publish(self, *, experiment_id: UUID) -> AbExperimentView:
        """Generate 3 hypotheses, publish to ads cabinet, start measurement window."""

        experiment = await self._repository.get_experiment(experiment_id=experiment_id)
        if experiment is None:
            raise AbTestNotFoundError("A/B experiment not found.")
        if experiment.status == AbExperimentStatus.COMPLETED:
            return experiment
        if experiment.status == AbExperimentStatus.FAILED:
            raise AbTestError(
                experiment.error_message or "A/B experiment previously failed."
            )
        if experiment.status == AbExperimentStatus.MEASURING:
            return experiment

        try:
            product = AbProductBrief.model_validate(experiment.product_payload)
            config = AbTestConfig.model_validate(experiment.config)

            await self._repository.mark_status(
                experiment_id=experiment_id,
                status=AbExperimentStatus.GENERATING,
            )

            hypotheses, tokens_in, tokens_out = await self._generate_hypotheses(
                product=product,
                user_id=experiment.user_id,
                experiment_id=experiment_id,
            )
            await self._write_stage_cache(
                experiment_id,
                "hypotheses",
                dump_hypotheses(hypotheses),
            )
            experiment = await self._repository.save_hypotheses(
                experiment_id=experiment_id,
                hypotheses=dump_hypotheses(hypotheses),
                input_tokens_delta=tokens_in,
                output_tokens_delta=tokens_out,
            )

            await self._repository.mark_status(
                experiment_id=experiment_id,
                status=AbExperimentStatus.PUBLISHING,
            )

            credentials = await self._load_credentials(
                user_id=experiment.user_id,
                platform=product.marketplace,
            )
            ads = self._build_ads_client(product.marketplace)

            try:
                hyp_by_strategy = {h.strategy: h for h in hypotheses}
                for variant in experiment.variants:
                    hyp = hyp_by_strategy.get(variant.strategy)
                    if hyp is None:
                        await self._repository.update_variant(
                            variant_id=variant.id,
                            status=AbVariantStatus.FAILED,
                            error_message="Missing hypothesis for strategy.",
                        )
                        continue
                    try:
                        published = await ads.publish_creative(
                            credentials=credentials,
                            product=product,
                            hypothesis=hyp,
                            campaign_id=product.campaign_id,
                        )
                        await self._repository.update_variant(
                            variant_id=variant.id,
                            status=AbVariantStatus.MEASURING,
                            ads_creative_id=published.get("creative_id"),
                            ads_campaign_id=published.get("campaign_id"),
                            marketplace_media_id=published.get("media_id"),
                            clear_error=True,
                        )
                    except Exception as exc:
                        logger.exception(
                            "Failed to publish A/B variant experiment=%s strategy=%s",
                            experiment_id,
                            variant.strategy.value,
                        )
                        await self._repository.update_variant(
                            variant_id=variant.id,
                            status=AbVariantStatus.FAILED,
                            error_message=str(exc)[:2000],
                        )
            finally:
                await ads.aclose()

            experiment = await self._repository.get_experiment(
                experiment_id=experiment_id
            )
            if experiment is None:
                raise AbTestNotFoundError("A/B experiment not found.")

            published_ok = [
                v
                for v in experiment.variants
                if v.status == AbVariantStatus.MEASURING and v.ads_creative_id
            ]
            if not published_ok:
                return await self._repository.mark_status(
                    experiment_id=experiment_id,
                    status=AbExperimentStatus.FAILED,
                    error_message="All creative variants failed to publish to ads cabinet.",
                    completed_at=datetime.now(UTC),
                )

            started = datetime.now(UTC)
            ends = measurement_window_end(
                started_at=started,
                duration_days=config.duration_days,
            )
            return await self._repository.mark_status(
                experiment_id=experiment_id,
                status=AbExperimentStatus.MEASURING,
                measurement_started_at=started,
                measurement_ends_at=ends,
            )
        except AbTestError:
            raise
        except Exception as exc:
            logger.exception("A/B generate/publish failed experiment_id=%s", experiment_id)
            await self._repository.mark_status(
                experiment_id=experiment_id,
                status=AbExperimentStatus.FAILED,
                error_message=str(exc)[:2000],
                completed_at=datetime.now(UTC),
            )
            raise AbTestError(str(exc)) from exc

    async def refresh_metrics(self, *, experiment_id: UUID) -> AbExperimentView:
        """Pull CTR snapshots for all measuring variants."""

        experiment = await self._repository.get_experiment(experiment_id=experiment_id)
        if experiment is None:
            raise AbTestNotFoundError("A/B experiment not found.")
        if experiment.status != AbExperimentStatus.MEASURING:
            return experiment

        product = AbProductBrief.model_validate(experiment.product_payload)
        credentials = await self._load_credentials(
            user_id=experiment.user_id,
            platform=product.marketplace,
        )
        ads = self._build_ads_client(product.marketplace)
        try:
            for variant in experiment.variants:
                if not variant.ads_creative_id:
                    continue
                if variant.status not in (
                    AbVariantStatus.MEASURING,
                    AbVariantStatus.PUBLISHED,
                ):
                    continue
                try:
                    metrics = await ads.fetch_creative_metrics(
                        credentials=credentials,
                        creative_id=variant.ads_creative_id,
                        campaign_id=variant.ads_campaign_id,
                    )
                    await self._repository.update_variant(
                        variant_id=variant.id,
                        metrics=metrics,
                        clear_error=True,
                    )
                except Exception as exc:
                    logger.warning(
                        "CTR poll failed experiment=%s variant=%s: %s",
                        experiment_id,
                        variant.id,
                        exc,
                    )
                    await self._repository.update_variant(
                        variant_id=variant.id,
                        error_message=f"CTR poll: {exc}"[:2000],
                    )
        finally:
            await ads.aclose()

        refreshed = await self._repository.get_experiment(experiment_id=experiment_id)
        if refreshed is None:
            raise AbTestNotFoundError("A/B experiment not found.")
        return refreshed

    async def resolve_experiment(
        self, *, experiment_id: UUID, force: bool = False
    ) -> AbExperimentView:
        """Keep the best CTR variant; delete losers from the ads cabinet."""

        experiment = await self._repository.get_experiment(experiment_id=experiment_id)
        if experiment is None:
            raise AbTestNotFoundError("A/B experiment not found.")
        if experiment.status == AbExperimentStatus.COMPLETED:
            return experiment
        if experiment.status == AbExperimentStatus.FAILED:
            raise AbTestError(
                experiment.error_message or "A/B experiment previously failed."
            )

        config = AbTestConfig.model_validate(experiment.config)
        if (
            not force
            and experiment.measurement_ends_at is not None
            and not is_measurement_complete(
                measurement_ends_at=experiment.measurement_ends_at
            )
        ):
            raise AbTestValidationError(
                "Measurement window has not ended yet; pass force=true to resolve early."
            )

        await self._repository.mark_status(
            experiment_id=experiment_id,
            status=AbExperimentStatus.RESOLVING,
        )

        # Fresh metrics before decision.
        if experiment.status == AbExperimentStatus.MEASURING or force:
            try:
                experiment = await self.refresh_metrics(experiment_id=experiment_id)
            except AbTestCredentialsError:
                logger.warning(
                    "Resolving A/B without fresh metrics (credentials missing) id=%s",
                    experiment_id,
                )
                experiment = await self._repository.get_experiment(
                    experiment_id=experiment_id
                ) or experiment

        product = AbProductBrief.model_validate(experiment.product_payload)
        resolution = build_resolution_result(
            variants=experiment.variants,
            config=config,
        )

        deleted_ids: list[UUID] = []
        kept_creative: str | None = resolution.kept_ads_creative_id

        if config.auto_delete_losers or config.auto_promote_winner:
            try:
                credentials = await self._load_credentials(
                    user_id=experiment.user_id,
                    platform=product.marketplace,
                )
                ads = self._build_ads_client(product.marketplace)
                try:
                    if (
                        config.auto_promote_winner
                        and resolution.winner_variant_id is not None
                    ):
                        winner = next(
                            (
                                v
                                for v in experiment.variants
                                if v.id == resolution.winner_variant_id
                            ),
                            None,
                        )
                        if winner and winner.ads_creative_id:
                            kept_creative = await ads.promote_winner(
                                credentials=credentials,
                                creative_id=winner.ads_creative_id,
                                campaign_id=winner.ads_campaign_id,
                                product=product,
                            )

                    if config.auto_delete_losers:
                        for variant in experiment.variants:
                            if (
                                resolution.winner_variant_id is not None
                                and variant.id == resolution.winner_variant_id
                            ):
                                continue
                            if not variant.ads_creative_id:
                                continue
                            ok = await ads.delete_creative(
                                credentials=credentials,
                                creative_id=variant.ads_creative_id,
                                campaign_id=variant.ads_campaign_id,
                            )
                            if ok:
                                deleted_ids.append(variant.id)
                finally:
                    await ads.aclose()
            except AbTestCredentialsError as exc:
                resolution.decision_notes.append(
                    f"Ads cabinet credentials unavailable during resolve: {exc}"
                )

        resolution = resolution.model_copy(
            update={
                "deleted_variant_ids": deleted_ids,
                "kept_ads_creative_id": kept_creative,
            }
        )
        await self._write_stage_cache(
            experiment_id,
            "resolution",
            dump_resolution(resolution),
        )

        return await self._repository.save_final_resolution(
            experiment_id=experiment_id,
            resolution_result=dump_resolution(resolution),
            winner_variant_id=resolution.winner_variant_id,
            winner_status=AbVariantStatus.WINNER,
            loser_ids=resolution.loser_variant_ids,
            deleted_ids=deleted_ids,
        )

    async def poll_active_experiments(self, *, limit: int = 50) -> dict[str, int]:
        """Beat entry: refresh CTR and auto-resolve experiments past the week window."""

        refreshed = 0
        resolved = 0
        failed = 0

        measuring = await self._repository.list_active_measuring(limit=limit)
        for experiment in measuring:
            try:
                await self.refresh_metrics(experiment_id=experiment.id)
                refreshed += 1
            except Exception as exc:
                failed += 1
                logger.warning(
                    "A/B metrics poll failed experiment=%s: %s",
                    experiment.id,
                    exc,
                )

        due = await self._repository.list_due_for_resolution(
            now=datetime.now(UTC),
            limit=limit,
        )
        for experiment in due:
            try:
                await self.resolve_experiment(experiment_id=experiment.id, force=False)
                resolved += 1
            except Exception as exc:
                failed += 1
                logger.exception(
                    "A/B auto-resolve failed experiment=%s: %s",
                    experiment.id,
                    exc,
                )
                await self._repository.mark_status(
                    experiment_id=experiment.id,
                    status=AbExperimentStatus.FAILED,
                    error_message=f"Auto-resolve failed: {exc}"[:2000],
                    completed_at=datetime.now(UTC),
                )

        return {
            "refreshed": refreshed,
            "resolved": resolved,
            "failed": failed,
            "measuring_seen": len(measuring),
            "due_seen": len(due),
        }

    async def _generate_hypotheses(
        self,
        *,
        product: AbProductBrief,
        user_id: UUID,
        experiment_id: UUID,
    ) -> tuple[tuple[AbVariantHypothesis, ...], int, int]:
        if self._hypothesis_generator is not None:
            try:
                hypotheses, tokens_in, tokens_out = (
                    await self._hypothesis_generator.generate_ab_hypotheses(
                        product=product,
                        user_id=user_id,
                        experiment_id=experiment_id,
                    )
                )
                return normalize_hypotheses(list(hypotheses)), tokens_in, tokens_out
            except Exception as exc:
                logger.warning(
                    "Claude A/B hypothesis generation failed; using deterministic "
                    "fallback experiment_id=%s: %s",
                    experiment_id,
                    exc,
                )
        return build_deterministic_hypotheses(product), 0, 0

    async def _load_credentials(
        self, *, user_id: UUID, platform: str
    ) -> dict[str, str]:
        if self._credentials is None:
            if self._allow_ads_fallback:
                return {"api_token": "local-dev-token"}
            raise AbTestCredentialsError("Credentials port is not configured.")
        try:
            secrets = await self._credentials.get_ads_credentials(
                user_id=user_id,
                platform=platform,
            )
        except Exception as exc:
            if self._allow_ads_fallback:
                logger.warning(
                    "Ads credentials unavailable for user=%s platform=%s; "
                    "using local fallback: %s",
                    user_id,
                    platform,
                    exc,
                )
                return {"api_token": "local-dev-token"}
            raise AbTestCredentialsError(str(exc)) from exc
        if not secrets:
            if self._allow_ads_fallback:
                return {"api_token": "local-dev-token"}
            raise AbTestCredentialsError(
                f"No marketplace credentials stored for platform={platform}."
            )
        return secrets

    def _build_ads_client(self, marketplace: str) -> MarketplaceAdsPort:
        if self._ads_client_factory is None:
            raise AbTestError("Ads client factory is not configured.")
        return self._ads_client_factory(marketplace)

    async def _write_stage_cache(
        self, experiment_id: UUID, stage: str, payload: Any
    ) -> None:
        try:
            await cache_json(
                redis_ab_stage_key(experiment_id, stage),
                payload,
                ttl_seconds=self._redis_stage_ttl_seconds,
            )
        except RedisUnavailableError:
            logger.debug("Redis unavailable for A/B stage cache %s", stage)
        except Exception:
            logger.debug("Failed to cache A/B stage %s", stage, exc_info=True)

    async def read_stage_cache(
        self, experiment_id: UUID, stage: str
    ) -> Any | None:
        try:
            return await get_cached_json(redis_ab_stage_key(experiment_id, stage))
        except Exception:
            return None
