"""LoRA training providers: Replicate (real weights) + synthetic BrandDNA fallback."""

from __future__ import annotations

import logging
from uuid import uuid4

import httpx

from app.core.config import Settings, get_settings
from app.domain.brand_lora import (
    LoraTrainingPollResult,
    LoraTrainingStartResult,
    map_provider_status,
    synthesize_brand_style_prompt,
)
from app.infrastructure.redis import RedisUnavailableError, cache_json, get_cached_json

logger = logging.getLogger(__name__)

_SYNTHETIC_JOB_TTL_SECONDS = 7 * 24 * 3600


class BrandLoraTrainingError(Exception):
    """Raised when the external LoRA trainer rejects or fails a request."""


def _synthetic_redis_key(training_id: str) -> str:
    return f"brand_lora:synthetic:{training_id}"


def _poll_from_payload(
    training_id: str, payload: dict
) -> LoraTrainingPollResult:
    return LoraTrainingPollResult(
        training_id=training_id,
        status=str(payload.get("status") or "succeeded"),
        progress=int(payload.get("progress") or 100),
        weights_url=payload.get("weights_url"),
        version_id=payload.get("version_id"),
        error_message=payload.get("error_message"),
        brand_style_prompt=payload.get("brand_style_prompt"),
    )


class SyntheticBrandLoraTrainer:
    """Dev / Midjourney path: synthesize BrandDNA prompt without GPU training.

    Results are mirrored to Redis so Celery worker restarts (new trainer
    instance) still poll the same DNA instead of inventing a wrong trigger.
    """

    name = "synthetic-brand-dna"

    def __init__(self) -> None:
        self._jobs: dict[str, LoraTrainingPollResult] = {}

    async def start_training(
        self,
        *,
        trigger_word: str,
        brand_name: str,
        notes: str | None,
        reference_object_keys: tuple[str, ...],
        dataset_zip_bytes: bytes | None = None,
    ) -> LoraTrainingStartResult:
        _ = dataset_zip_bytes
        training_id = f"synthetic-{uuid4().hex}"
        prompt = synthesize_brand_style_prompt(
            brand_name=brand_name,
            trigger_word=trigger_word,
            notes=notes,
        )
        if reference_object_keys:
            prompt = (
                f"{prompt}, trained on {len(reference_object_keys)} brand "
                "reference frames"
            )
        result = LoraTrainingPollResult(
            training_id=training_id,
            status="succeeded",
            progress=100,
            weights_url=None,
            version_id=f"synthetic-v-{trigger_word}",
            error_message=None,
            brand_style_prompt=prompt,
        )
        self._jobs[training_id] = result
        try:
            await cache_json(
                _synthetic_redis_key(training_id),
                {
                    "status": result.status,
                    "progress": result.progress,
                    "weights_url": result.weights_url,
                    "version_id": result.version_id,
                    "error_message": result.error_message,
                    "brand_style_prompt": result.brand_style_prompt,
                    "trigger_word": trigger_word,
                    "brand_name": brand_name,
                },
                _SYNTHETIC_JOB_TTL_SECONDS,
            )
        except RedisUnavailableError:
            logger.warning(
                "Redis unavailable; synthetic BrandDNA kept in-process only id=%s",
                training_id,
            )
        logger.info(
            "Synthetic BrandDNA trained training_id=%s refs=%s",
            training_id,
            len(reference_object_keys),
        )
        return LoraTrainingStartResult(training_id=training_id, status="starting")

    async def poll_training(self, *, training_id: str) -> LoraTrainingPollResult:
        job = self._jobs.get(training_id)
        if job is not None:
            return job
        try:
            cached = await get_cached_json(_synthetic_redis_key(training_id))
        except RedisUnavailableError:
            cached = None
        if cached is not None:
            result = _poll_from_payload(training_id, cached)
            self._jobs[training_id] = result
            return result
        # Last-resort restart path: rebuild DNA from the training id slug only
        # when Redis and process memory are both empty (should be rare).
        trigger = training_id.replace("synthetic-", "brnd")[:28]
        prompt = synthesize_brand_style_prompt(
            brand_name="Brand",
            trigger_word=trigger,
            notes=None,
        )
        return LoraTrainingPollResult(
            training_id=training_id,
            status="succeeded",
            progress=100,
            weights_url=None,
            version_id=None,
            error_message=None,
            brand_style_prompt=prompt,
        )


class ReplicateLoraTrainer:
    """Train a real LoRA via Replicate's training API.

    Prefers an uploaded dataset ZIP (presigned S3 URL). Falls back to
    ``REPLICATE_LORA_DATASET_URL_OVERRIDE`` when ZIP bytes are absent.
    """

    name = "replicate"

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        token = (
            self._settings.replicate_api_token.get_secret_value()
            if self._settings.replicate_api_token is not None
            else ""
        )
        if not token.strip():
            raise BrandLoraTrainingError("REPLICATE_API_TOKEN is not configured.")
        self._token = token.strip()
        self._base_url = self._settings.replicate_api_base_url.rstrip("/")
        self._timeout = self._settings.replicate_timeout_seconds

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
            "Prefer": "wait",
        }

    async def _resolve_dataset_url(
        self,
        *,
        trigger_word: str,
        dataset_zip_bytes: bytes | None,
    ) -> str:
        override = self._settings.replicate_lora_dataset_url_override.strip()
        if dataset_zip_bytes:
            from app.services.s3_storage import get_s3_storage

            object_key = f"brand-lora/datasets/{trigger_word}-{uuid4().hex}.zip"
            uploaded = await get_s3_storage().upload_bytes(
                object_key=object_key,
                data=dataset_zip_bytes,
                content_type="application/zip",
                presign=True,
            )
            if uploaded.presigned_url:
                return uploaded.presigned_url
        if override:
            return override
        raise BrandLoraTrainingError(
            "Replicate LoRA training requires dataset ZIP bytes or "
            "REPLICATE_LORA_DATASET_URL_OVERRIDE."
        )

    async def start_training(
        self,
        *,
        trigger_word: str,
        brand_name: str,
        notes: str | None,
        reference_object_keys: tuple[str, ...],
        dataset_zip_bytes: bytes | None = None,
    ) -> LoraTrainingStartResult:
        _ = notes
        if not reference_object_keys and not dataset_zip_bytes:
            raise BrandLoraTrainingError("LoRA training requires reference object keys.")
        dataset_url = await self._resolve_dataset_url(
            trigger_word=trigger_word,
            dataset_zip_bytes=dataset_zip_bytes,
        )
        destination = self._settings.replicate_lora_destination.strip()
        if not destination or "/" not in destination:
            raise BrandLoraTrainingError(
                "REPLICATE_LORA_DESTINATION must be 'owner/model-name'."
            )
        owner, model = destination.split("/", 1)
        payload = {
            "destination": f"{owner}/{model}",
            "input": {
                "input_images": dataset_url,
                "trigger_word": trigger_word,
                "lora_type": "style",
                "steps": self._settings.replicate_lora_training_steps,
            },
        }
        url = (
            f"{self._base_url}/models/"
            f"{self._settings.replicate_lora_trainer_model}/versions/"
            f"{self._settings.replicate_lora_trainer_version}/trainings"
        )
        trainings_url = (
            f"{self._base_url}/models/{owner}/{model}/versions/"
            f"{self._settings.replicate_lora_trainer_version}/trainings"
            if self._settings.replicate_lora_use_model_trainings_endpoint
            else url
        )
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.post(
                trainings_url,
                headers=self._headers(),
                json=payload,
            )
        if response.status_code >= 400:
            raise BrandLoraTrainingError(
                f"Replicate training start failed ({response.status_code}): "
                f"{response.text[:400]}"
            )
        body = response.json()
        training_id = str(body.get("id") or "").strip()
        if not training_id:
            raise BrandLoraTrainingError("Replicate response missing training id.")
        logger.info(
            "Replicate LoRA training started id=%s brand=%s dataset=%s",
            training_id,
            brand_name,
            dataset_url[:80],
        )
        return LoraTrainingStartResult(
            training_id=training_id,
            status=str(body.get("status") or "starting"),
        )

    async def poll_training(self, *, training_id: str) -> LoraTrainingPollResult:
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.get(
                f"{self._base_url}/trainings/{training_id}",
                headers=self._headers(),
            )
        if response.status_code >= 400:
            raise BrandLoraTrainingError(
                f"Replicate poll failed ({response.status_code}): "
                f"{response.text[:400]}"
            )
        body = response.json()
        raw_status = str(body.get("status") or "processing")
        domain_status = map_provider_status(raw_status)
        error = body.get("error")
        output = body.get("output")
        weights_url: str | None = None
        version_id = str(body.get("version") or "") or None
        if isinstance(output, str) and output.startswith("http"):
            weights_url = output
        elif isinstance(output, dict):
            for key in ("weights", "version", "url", "lora"):
                value = output.get(key)
                if isinstance(value, str) and value.startswith("http"):
                    weights_url = value
                    break
        progress = 100 if domain_status.value == "ready" else 50
        if domain_status.value == "queued":
            progress = 10
        elif domain_status.value == "training":
            progress = 55
        elif domain_status.value == "failed":
            progress = 100
        return LoraTrainingPollResult(
            training_id=training_id,
            status=raw_status,
            progress=progress,
            weights_url=weights_url,
            version_id=version_id,
            error_message=str(error) if error else None,
            brand_style_prompt=None,
        )


def build_lora_training_provider(
    settings: Settings | None = None,
) -> SyntheticBrandLoraTrainer | ReplicateLoraTrainer:
    """Prefer Replicate when token + destination are set; else BrandDNA synthetic."""

    cfg = settings or get_settings()
    token = (
        cfg.replicate_api_token.get_secret_value()
        if cfg.replicate_api_token is not None
        else ""
    )
    if (
        cfg.brand_lora_prefer_replicate
        and token.strip()
        and cfg.replicate_lora_destination.strip()
    ):
        try:
            return ReplicateLoraTrainer(cfg)
        except BrandLoraTrainingError:
            logger.warning("Replicate LoRA trainer unavailable; using synthetic DNA")
    return SyntheticBrandLoraTrainer()
