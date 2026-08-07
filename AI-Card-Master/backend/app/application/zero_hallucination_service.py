"""Zero-Hallucination Cross-Check use cases (plan §57)."""

from __future__ import annotations

import logging
from uuid import UUID

from app.application.ports.zero_hallucination import ZeroHallucinationCrossCheckPort
from app.domain.zero_hallucination import (
    ZeroHallucinationCrossCheck,
    build_insufficient_cross_check,
    finalize_cross_check,
)

logger = logging.getLogger(__name__)


class ZeroHallucinationValidationError(ValueError):
    """Invalid dual-check inputs."""


class ZeroHallucinationService:
    """Orchestrate OCR ↔ description dual verification + reliability scoring."""

    def __init__(
        self,
        checker: ZeroHallucinationCrossCheckPort | None,
        *,
        enabled: bool = True,
        max_vision_images: int = 5,
    ) -> None:
        if max_vision_images < 1:
            raise ZeroHallucinationValidationError("max_vision_images must be >= 1.")
        self._checker = checker
        self._enabled = enabled
        self._max_vision_images = max_vision_images

    @property
    def enabled(self) -> bool:
        return self._enabled and self._checker is not None

    async def cross_check_card(
        self,
        *,
        images: tuple[tuple[bytes, str], ...],
        title: str | None,
        description: str | None,
        specs: list[str],
        marketplace: str | None = None,
        article: str | None = None,
        user_id: UUID | None = None,
        job_id: UUID | None = None,
    ) -> tuple[ZeroHallucinationCrossCheck, int, int]:
        """Run dual check; return (result, input_tokens, output_tokens).

        Never raises on sparse data — returns insufficient_data with 0% reliability.
        """

        model_name = self._checker.model_name if self._checker is not None else ""
        if not self._enabled:
            return (
                build_insufficient_cross_check(
                    reason="Zero-Hallucination Cross-Check disabled by config.",
                    model_name=model_name,
                ),
                0,
                0,
            )
        if self._checker is None:
            return (
                build_insufficient_cross_check(
                    reason=(
                        "Claude is not configured; refusing to invent OCR claims "
                        "without Vision evidence."
                    ),
                    model_name="",
                ),
                0,
                0,
            )

        selected = images[: self._max_vision_images]
        desc = (description or "").strip()
        if not selected:
            return (
                build_insufficient_cross_check(
                    reason="No competitor images available for OCR dual-check.",
                    model_name=model_name,
                ),
                0,
                0,
            )
        if not desc and not any((s or "").strip() for s in specs) and not (title or "").strip():
            return (
                build_insufficient_cross_check(
                    reason=(
                        "No title/description/specs to compare against OCR claims."
                    ),
                    model_name=model_name,
                ),
                0,
                0,
            )

        try:
            payload, in_tok, out_tok = await self._checker.extract_and_cross_check(
                images=selected,
                title=title,
                description=description,
                specs=list(specs),
                marketplace=marketplace,
                article=article,
                user_id=user_id,
                job_id=job_id,
            )
        except Exception:
            logger.exception(
                "Zero-Hallucination cross-check failed article=%s job_id=%s",
                article,
                job_id,
            )
            return (
                build_insufficient_cross_check(
                    reason=(
                        "Claude OCR cross-check failed; advice reliability set to 0% "
                        "to avoid hallucinated recommendations."
                    ),
                    model_name=model_name,
                ),
                0,
                0,
            )

        result = finalize_cross_check(
            payload,
            description=description,
            model_name=model_name,
        )
        logger.info(
            "Zero-Hallucination cross-check article=%s verdict=%s "
            "reliability=%s%% contradictions=%s",
            article,
            result.verdict.value,
            result.advice_reliability_pct,
            len(result.contradictions),
        )
        return result, in_tok, out_tok

    async def aclose(self) -> None:
        if self._checker is not None:
            await self._checker.aclose()
