"""Helpers for persisting third-party API usage cost events."""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any
from uuid import UUID

from app.models.api_usage_cost import ApiUsageCost
from app.models.database import SessionLocal

logger = logging.getLogger(__name__)


async def record_api_usage_cost(
    *,
    provider: str,
    operation: str,
    model_name: str | None,
    units: int,
    unit_cost_usd: Decimal,
    total_cost_usd: Decimal,
    user_id: UUID | None = None,
    generation_job_id: UUID | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    """Persist one provider cost event without leaking failures to callers."""

    try:
        async with SessionLocal() as session:
            session.add(
                ApiUsageCost(
                    user_id=user_id,
                    generation_job_id=generation_job_id,
                    provider=provider,
                    model_name=model_name,
                    operation=operation,
                    units=units,
                    unit_cost_usd=unit_cost_usd,
                    total_cost_usd=total_cost_usd,
                    usage_metadata=metadata,
                )
            )
            await session.commit()
    except Exception:
        logger.warning("Failed to persist API usage cost event", exc_info=True)
