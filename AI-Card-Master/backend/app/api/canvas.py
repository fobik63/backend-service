"""REST API: ephemeral canvas composite (CanvasStateDTO → PNG/WebP).

Used by the Next.js editor for live previews without persisting a design row.
"""

from __future__ import annotations

import logging
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from app.api.payments import get_current_user
from app.models.user import User
from app.schemas.templates import CanvasStateDTO
from app.services.templates.renderer import (
    CanvasRenderError,
    CanvasServerRenderer,
    get_canvas_server_renderer,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/canvas", tags=["canvas"])


def _get_renderer() -> CanvasServerRenderer:
    return get_canvas_server_renderer()


@router.post(
    "/render",
    status_code=status.HTTP_200_OK,
    summary="Render CanvasStateDTO to PNG/WebP bytes",
    description=(
        "Composites the submitted canvas document server-side (Pillow) and "
        "returns raw image bytes. Prefer this for editor live preview; use "
        "POST /api/v1/designs/{id}/render to persist + upload to S3."
    ),
    responses={
        200: {
            "content": {
                "image/png": {},
                "image/webp": {},
            },
            "description": "Rendered card image",
        }
    },
)
async def render_canvas(
    body: CanvasStateDTO,
    current_user: Annotated[User, Depends(get_current_user)],
    renderer: Annotated[CanvasServerRenderer, Depends(_get_renderer)],
    output_format: Annotated[
        Literal["png", "webp"],
        Query(description="Output image codec"),
    ] = "png",
) -> Response:
    del current_user  # auth gate only

    try:
        result = await renderer.render(body, output_format=output_format)
    except CanvasRenderError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    except Exception as exc:  # noqa: BLE001
        logger.exception("Canvas render failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Canvas render failed.",
        ) from exc

    media = "image/webp" if output_format == "webp" else "image/png"
    return Response(
        content=result.image_bytes,
        media_type=media,
        headers={
            "Cache-Control": "no-store",
            "X-Canvas-Width": str(result.width),
            "X-Canvas-Height": str(result.height),
        },
    )
