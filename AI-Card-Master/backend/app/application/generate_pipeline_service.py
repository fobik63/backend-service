"""Application service: frontend product params → n8n → structured layers/badges."""

from __future__ import annotations

import logging
from uuid import UUID, uuid4

from pydantic import ValidationError

from app.application.generate_pipeline_errors import (
    GeneratePipelineError,
    GeneratePipelineInternalError,
    GeneratePipelineValidationError,
)
from app.infrastructure.n8n_pipeline_client import N8nPipelineClient
from app.schemas.generate_pipeline import (
    GeneratePipelineRequest,
    GeneratePipelineResponse,
    N8nPipelineResult,
)

logger = logging.getLogger(__name__)


class GeneratePipelineService:
    """Orchestrate one synchronous n8n generate-pipeline round-trip."""

    def __init__(self, client: N8nPipelineClient | None = None) -> None:
        self._client = client or N8nPipelineClient()

    async def run(
        self,
        *,
        user_id: UUID,
        body: GeneratePipelineRequest,
        request_id: UUID | None = None,
    ) -> GeneratePipelineResponse:
        correlation_id = request_id or uuid4()
        outbound = body.to_n8n_payload(request_id=correlation_id, user_id=user_id)

        logger.info(
            "generate-pipeline start request_id=%s user_id=%s product=%s marketplace=%s",
            correlation_id,
            user_id,
            body.product_name,
            body.marketplace,
        )

        try:
            raw = await self._client.invoke(outbound)
            result = N8nPipelineResult.model_validate(raw)
        except GeneratePipelineError:
            raise
        except ValidationError as exc:
            logger.warning(
                "generate-pipeline invalid n8n payload request_id=%s errors=%s",
                correlation_id,
                exc.errors(),
            )
            raise GeneratePipelineValidationError(
                "n8n response failed validation (expected layers + badges).",
            ) from exc
        except Exception as exc:  # noqa: BLE001 — last-resort guard
            logger.exception(
                "generate-pipeline unexpected failure request_id=%s user_id=%s",
                correlation_id,
                user_id,
            )
            raise GeneratePipelineInternalError(
                "Unexpected error while running the generate pipeline.",
            ) from exc

        logger.info(
            "generate-pipeline success request_id=%s badges=%s",
            correlation_id,
            len(result.badges),
        )
        return GeneratePipelineResponse(
            success=True,
            request_id=correlation_id,
            layers=result.layers,
            badges=result.badges,
            product_name=body.product_name,
        )
