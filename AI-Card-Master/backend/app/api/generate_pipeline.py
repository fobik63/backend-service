"""HTTP controller: POST /api/v1/generate-pipeline → n8n → structured JSON."""

from __future__ import annotations

import logging
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.api.dependencies.auth import get_current_user
from app.application.generate_pipeline_errors import GeneratePipelineError
from app.application.generate_pipeline_service import GeneratePipelineService
from app.core.rate_limit import generations_user_limit
from app.models.user import User
from app.schemas.generate_pipeline import (
    GeneratePipelineRequest,
    GeneratePipelineResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/generate-pipeline", tags=["generate-pipeline"])


def get_generate_pipeline_service() -> GeneratePipelineService:
    return GeneratePipelineService()


def _map_pipeline_error(exc: GeneratePipelineError) -> HTTPException:
    return HTTPException(
        status_code=exc.status_code,
        detail={"code": exc.code, "message": exc.message},
    )


@router.post(
    "",
    response_model=GeneratePipelineResponse,
    status_code=status.HTTP_200_OK,
    summary="Run the n8n generate-pipeline for a product card",
    description=(
        "Forwards validated product parameters to the configured n8n webhook, "
        "waits for the workflow ``Respond to Webhook`` payload "
        "(layer image URLs + badges/plaques), and returns structured JSON "
        "for the editor frontend."
    ),
)
@generations_user_limit
async def run_generate_pipeline(
    request: Request,
    body: GeneratePipelineRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[
        GeneratePipelineService,
        Depends(get_generate_pipeline_service),
    ],
) -> GeneratePipelineResponse:
    request_id = uuid4()
    try:
        return await service.run(
            user_id=current_user.id,
            body=body,
            request_id=request_id,
        )
    except GeneratePipelineError as exc:
        logger.warning(
            "generate-pipeline rejected request_id=%s user_id=%s code=%s message=%s",
            request_id,
            current_user.id,
            exc.code,
            exc.message,
        )
        raise _map_pipeline_error(exc) from exc
    except Exception as exc:  # noqa: BLE001 — never leak internals to the client
        logger.exception(
            "generate-pipeline unhandled error request_id=%s user_id=%s",
            request_id,
            current_user.id,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "code": "generate_pipeline_internal_error",
                "message": "Unexpected error while running the generate pipeline.",
            },
        ) from exc
