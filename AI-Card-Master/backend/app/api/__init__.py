"""API layer: routers and endpoint handlers."""

from app.api.account import router as account_router
from app.api.admin import router as admin_router
from app.api.admin import security_status_ws_router as admin_security_ws_router
from app.api.ab_tests import router as ab_tests_router
from app.api.ai_strategy import router as ai_strategy_router
from app.api.analytics import router as analytics_router
from app.api.auth import router as auth_router
from app.api.bg_removal import router as bg_removal_router
from app.api.brand_loras import router as brand_loras_router
from app.api.brand_dna import router as brand_dna_router
from app.api.bulk_generations import router as bulk_generations_router
from app.api.canvas import router as canvas_router
from app.api.captcha import router as captcha_router
from app.api.claude_analyses import router as claude_analyses_router
from app.api.claude_reasoning import router as claude_reasoning_router
from app.api.exports import router as exports_router
from app.api.parser import router as parser_router
from app.api.generations import router as generations_router
from app.api.health import router as health_router
from app.api.images import router as images_router
from app.api.fonts import router as fonts_router
from app.api.legal import router as legal_router
from app.api.marketplace_bridge import router as marketplace_bridge_router
from app.api.oracle import router as oracle_router
from app.api.pain_analysis import router as pain_analysis_router
from app.api.payments import router as payments_router
from app.api.referrals import router as referrals_router
from app.api.relighting import router as relighting_router
from app.api.smart_variants import router as smart_variants_router
from app.api.templates import designs_router, templates_router
from app.api.text_generation import router as text_generation_router
from app.api.visual_audit import router as visual_audit_router
from app.api.webhooks import midjourney_webhook_router
from app.api.three_d import router as three_d_router
from app.api.three_d_video import router as three_d_video_router
from app.api.three_d_ws import router as three_d_ws_router
from app.api.winback import router as winback_router
from app.api.workspaces import router as workspaces_router

__all__ = [
    "account_router",
    "admin_router",
    "admin_security_ws_router",
    "ab_tests_router",
    "ai_strategy_router",
    "analytics_router",
    "auth_router",
    "bg_removal_router",
    "brand_loras_router",
    "brand_dna_router",
    "bulk_generations_router",
    "canvas_router",
    "captcha_router",
    "claude_analyses_router",
    "claude_reasoning_router",
    "designs_router",
    "exports_router",
    "fonts_router",
    "generations_router",
    "health_router",
    "images_router",
    "legal_router",
    "marketplace_bridge_router",
    "midjourney_webhook_router",
    "oracle_router",
    "pain_analysis_router",
    "parser_router",
    "payments_router",
    "referrals_router",
    "relighting_router",
    "smart_variants_router",
    "templates_router",
    "text_generation_router",
    "three_d_router",
    "three_d_video_router",
    "three_d_ws_router",
    "visual_audit_router",
    "winback_router",
    "workspaces_router",
]
