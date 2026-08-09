"""Wire SEO text use case to OpenAI provider + BillingService."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.application.seo_text_service import SEO_TEXT_COST_COINS, SeoTextService
from app.infrastructure.openai.seo_text_client import OpenAiSeoTextClient
from app.services.billing_service import BillingService


def build_seo_text_service(
    session: AsyncSession,
    *,
    provider: OpenAiSeoTextClient | None = None,
    billing: BillingService | None = None,
    cost_coins: int = SEO_TEXT_COST_COINS,
    charge_coins: bool | None = None,
) -> SeoTextService:
    """Construct the application service for ``/api/ai/generate-description``."""

    return SeoTextService(
        session,
        provider=provider or OpenAiSeoTextClient(),
        billing=billing,
        cost_coins=cost_coins,
        charge_coins=charge_coins,
    )
