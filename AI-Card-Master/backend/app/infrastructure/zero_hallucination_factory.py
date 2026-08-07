"""Composition root for Zero-Hallucination OCR ↔ description cross-check."""

from __future__ import annotations

from typing import Any

from app.application.zero_hallucination_service import ZeroHallucinationService
from app.core.config import Settings, get_settings
from app.domain.smart_reasoning import ReasoningTaskKind
from app.infrastructure.claude_client_loader import load_claude_client
from app.infrastructure.smart_reasoning_factory import (
    build_analytics_cache,
    resolve_claude_model,
)


def build_zero_hallucination_service(
    *,
    settings: Settings | None = None,
    require_claude_client: bool = False,
) -> ZeroHallucinationService:
    """Wire Claude Vision checker for competitor-audit / strategy composition."""

    cfg = settings or get_settings()
    checker = _build_claude_checker(cfg, require_claude_client=require_claude_client)
    return ZeroHallucinationService(
        checker,
        enabled=cfg.zero_hallucination_enabled,
        max_vision_images=cfg.zero_hallucination_max_vision_images,
    )


def _build_claude_checker(
    settings: Any,
    *,
    require_claude_client: bool,
) -> Any | None:
    task = ReasoningTaskKind.ZERO_HALLUCINATION
    return load_claude_client(
        settings,
        require=require_claude_client,
        model_name=resolve_claude_model(task, settings),
        analytics_cache=build_analytics_cache(),
        analytics_cache_ttl_seconds=settings.claude_analytics_cache_ttl_seconds,
        analytics_task_kind=task.value,
    )
