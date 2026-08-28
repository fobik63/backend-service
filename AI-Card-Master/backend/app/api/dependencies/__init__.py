"""Shared FastAPI dependencies that are independent of feature routers."""

from app.api.dependencies.auth import get_current_user
from app.api.dependencies.coin_guard import get_coin_guard_service
from app.api.dependencies.llm_coin_guard import (
    get_llm_coin_guard,
    require_review_coins,
    require_seo_card_coins,
)
from app.api.dependencies.yookassa_webhook import require_yookassa_webhook_source

__all__ = [
    "get_coin_guard_service",
    "get_current_user",
    "get_llm_coin_guard",
    "require_review_coins",
    "require_seo_card_coins",
    "require_yookassa_webhook_source",
]
