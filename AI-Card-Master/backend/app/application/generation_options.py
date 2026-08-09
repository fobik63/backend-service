"""Shared generation option parsing and entitlement checks."""

from __future__ import annotations

from app.application.generation_errors import GenerationForbiddenError
from app.core.pricing import generation_cost_for_mode
from app.domain.generation import GenerationEngineMode, GenerationPostProcessingMode
from app.models.user import User


def parse_engine_mode(value: object) -> GenerationEngineMode:
    if isinstance(value, GenerationEngineMode):
        return value
    if isinstance(value, str):
        cleaned = value.strip().lower()
        try:
            return GenerationEngineMode(cleaned)
        except ValueError as exc:
            raise ValueError("engine_mode must be 'standard' or 'premium'.") from exc
    raise ValueError("engine_mode must be 'standard' or 'premium'.")


def parse_post_processing_mode(value: object) -> GenerationPostProcessingMode:
    if isinstance(value, GenerationPostProcessingMode):
        return value
    if isinstance(value, str):
        cleaned = value.strip().lower()
        aliases = {
            "quick": GenerationPostProcessingMode.FAST,
            "fast_generation": GenerationPostProcessingMode.FAST,
            "hd": GenerationPostProcessingMode.HD_FACE_FIX,
            "hd_quality": GenerationPostProcessingMode.HD_FACE_FIX,
            "hd_quality_face_fix": GenerationPostProcessingMode.HD_FACE_FIX,
        }
        if cleaned in aliases:
            return aliases[cleaned]
        try:
            return GenerationPostProcessingMode(cleaned)
        except ValueError as exc:
            raise ValueError(
                "post_processing_mode must be 'fast' or 'hd_face_fix'."
            ) from exc
    raise ValueError("post_processing_mode must be 'fast' or 'hd_face_fix'.")


def effective_engine_mode(
    engine_mode: GenerationEngineMode,
    post_processing_mode: GenerationPostProcessingMode,
) -> GenerationEngineMode:
    if post_processing_mode == GenerationPostProcessingMode.HD_FACE_FIX:
        return GenerationEngineMode.PREMIUM
    return engine_mode


def ensure_generation_options_allowed(
    engine_mode: GenerationEngineMode,
    post_processing_mode: GenerationPostProcessingMode,
    user: User,
) -> None:
    if engine_mode == GenerationEngineMode.PREMIUM and not user.subscription_status.is_paid():
        raise GenerationForbiddenError(
            "Premium generation mode requires an active paid subscription."
        )
    if (
        post_processing_mode == GenerationPostProcessingMode.HD_FACE_FIX
        and not user.subscription_status.is_paid()
    ):
        raise GenerationForbiddenError(
            "HD Face Fix post-processing requires an active paid subscription."
        )


def cost_for_mode(post_processing_mode: GenerationPostProcessingMode) -> int:
    return generation_cost_for_mode(post_processing_mode)


def validate_owned_source_object_key(object_key: str, user_id: object) -> None:
    allowed_prefixes = (
        f"generation-inputs/{user_id}/",
        f"model-inputs/{user_id}/",
        f"user-uploads/{user_id}/",
    )
    if not object_key.startswith(allowed_prefixes):
        raise GenerationForbiddenError(
            "Source image object key does not belong to the current user."
        )
