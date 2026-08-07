"""Composition root helpers for Custom Brand LoRA (API + Celery)."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.application.brand_lora_service import BrandLoraService
from app.core.config import get_settings
from app.core.pricing import ServiceType, calculate_cost
from app.infrastructure.brand_lora_trainer import build_lora_training_provider
from app.infrastructure.persistence.brand_lora_repository import BrandLoraRepository
from app.services.s3_storage import get_s3_storage


def build_brand_lora_service(db_session: AsyncSession) -> BrandLoraService:
    """Wire ports for HTTP handlers and Celery workers."""

    settings = get_settings()
    return BrandLoraService(
        BrandLoraRepository(db_session),
        storage=get_s3_storage(),
        trainer=build_lora_training_provider(settings),
        min_references=settings.brand_lora_min_references,
        max_references=settings.brand_lora_max_references,
        max_image_bytes=settings.generation_max_upload_bytes,
        training_cost_coins=calculate_cost(
            ServiceType.BRAND_LORA.value, "train", {}, settings=settings
        ),
        charge_coins=settings.generation_charge_coins,
        auto_activate_on_ready=settings.brand_lora_auto_activate,
    )
