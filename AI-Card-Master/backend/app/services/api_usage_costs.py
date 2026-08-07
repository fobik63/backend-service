"""Helpers for persisting third-party API usage cost events (plan §80)."""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any
from uuid import UUID

from app.domain.cost_analytics import CostCallStatus, CostEventRecord
from app.infrastructure.persistence.cost_analytics_repository import CostAnalyticsRepository
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
    input_tokens: int = 0,
    output_tokens: int = 0,
    status: str | CostCallStatus = CostCallStatus.SUCCESS,
    duration_ms: int | None = None,
    task_id: UUID | None = None,
) -> None:
    """Persist one provider cost event + daily rollup without leaking failures."""

    try:
        if isinstance(status, CostCallStatus):
            call_status = status
        else:
            try:
                call_status = CostCallStatus(str(status))
            except ValueError:
                call_status = CostCallStatus.SUCCESS

        # Prefer explicit token args; fall back to metadata for legacy callers.
        meta = metadata or {}
        in_tokens = input_tokens
        out_tokens = output_tokens
        if in_tokens <= 0 and isinstance(meta.get("input_tokens"), int):
            in_tokens = max(0, int(meta["input_tokens"]))
        if out_tokens <= 0 and isinstance(meta.get("output_tokens"), int):
            out_tokens = max(0, int(meta["output_tokens"]))

        resolved_task_id = task_id
        if resolved_task_id is None:
            raw_task = meta.get("task_id") or meta.get("claude_reasoning_job_id")
            if raw_task:
                try:
                    resolved_task_id = UUID(str(raw_task))
                except (TypeError, ValueError):
                    resolved_task_id = None

        event = CostEventRecord(
            provider=provider,
            operation=operation,
            model_name=model_name,
            status=call_status,
            total_cost_usd=total_cost_usd,
            unit_cost_usd=unit_cost_usd,
            units=units,
            input_tokens=in_tokens,
            output_tokens=out_tokens,
            duration_ms=duration_ms,
            user_id=user_id,
            generation_job_id=generation_job_id,
            task_id=resolved_task_id,
            metadata=metadata,
        )
        async with SessionLocal() as session:
            await CostAnalyticsRepository(session).record_event(event)
    except Exception:
        logger.warning("Failed to persist API usage cost event", exc_info=True)
        try:
            from app.infrastructure.observability.metrics import (
                inc_cost_persist_failure,
            )

            inc_cost_persist_failure(provider=provider, operation=operation)
        except Exception:
            logger.debug("cost_persist_failures counter unavailable", exc_info=True)
