"""API layer: routers and endpoint handlers."""

from app.api.account import router as account_router
from app.api.admin import router as admin_router
from app.api.ab_tests import router as ab_tests_router
from app.api.ai_strategy import router as ai_strategy_router
from app.api.analytics import router as analytics_router
from app.api.bulk_generations import router as bulk_generations_router
from app.api.claude_analyses import router as claude_analyses_router
from app.api.claude_reasoning import router as claude_reasoning_router
from app.api.exports import router as exports_router
from app.api.generations import router as generations_router
from app.api.images import router as images_router
from app.api.legal import router as legal_router
from app.api.marketplace_bridge import router as marketplace_bridge_router
from app.api.oracle import router as oracle_router
from app.api.pain_analysis import router as pain_analysis_router
from app.api.payments import router as payments_router
from app.api.referrals import router as referrals_router
from app.api.smart_variants import router as smart_variants_router
from app.api.text_generation import router as text_generation_router
from app.api.visual_audit import router as visual_audit_router
from app.api.webhooks import midjourney_webhook_router
from app.api.winback import router as winback_router
from app.api.workspaces import router as workspaces_router

__all__ = [
    "account_router",
    "admin_router",
    "ab_tests_router",
    "ai_strategy_router",
    "analytics_router",
    "bulk_generations_router",
    "claude_analyses_router",
    "claude_reasoning_router",
    "exports_router",
    "generations_router",
    "images_router",
    "legal_router",
    "marketplace_bridge_router",
    "midjourney_webhook_router",
    "oracle_router",
    "pain_analysis_router",
    "payments_router",
    "referrals_router",
    "smart_variants_router",
    "text_generation_router",
    "visual_audit_router",
    "winback_router",
    "workspaces_router",
]
