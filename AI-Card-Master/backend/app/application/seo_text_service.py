"""Use case: generate WB/Ozon SEO copy and debit AI-coins (Safe Spend)."""

from __future__ import annotations

import logging
from typing import Any, Final
from uuid import UUID

from app.application.ports.seo_text import SeoTextProviderPort
from app.core.config import get_settings
from app.domain.seo_text import (
    SeoTextConfigurationError,
    SeoTextGenerateRequest,
    SeoTextGenerateResult,
    SeoTextUpstreamError,
    SeoTextValidationError,
)
from app.models.user import User
from app.services.billing_service import (
    BillingError,
    BillingNotFoundError,
    BillingService,
    BillingValidationError,
)

logger = logging.getLogger(__name__)

SEO_TEXT_COST_COINS: Final[int] = 1


class SeoTextService:
    """Debit → OpenAI SEO generation → refund-on-failure → commit."""

    def __init__(
        self,
        session: Any,
        *,
        provider: SeoTextProviderPort,
        billing: BillingService | None = None,
        cost_coins: int | None = None,
        charge_coins: bool | None = None,
    ) -> None:
        self._session = session
        self._provider = provider
        self._billing = billing or BillingService(session)
        settings = get_settings()
        if charge_coins is None:
            self._charge_coins = bool(settings.generation_charge_coins)
        else:
            self._charge_coins = bool(charge_coins)
        resolved_cost = (
            SEO_TEXT_COST_COINS if cost_coins is None else max(0, int(cost_coins))
        )
        self._cost_coins = resolved_cost if self._charge_coins else 0

    @property
    def cost_coins(self) -> int:
        return self._cost_coins

    async def generate(
        self,
        *,
        user_id: UUID,
        request: SeoTextGenerateRequest,
        idempotency_key: str | None = None,
    ) -> SeoTextGenerateResult:
        """Generate SEO artifacts and settle the AI-coin charge."""

        if not request.title.strip():
            raise SeoTextValidationError("title must not be empty.")
        if not request.category.strip():
            raise SeoTextValidationError("category must not be empty.")

        ensure = getattr(self._provider, "ensure_configured", None)
        if callable(ensure):
            ensure()

        user: User | None = None
        if self._cost_coins > 0:
            try:
                user = await self._billing.debit_coins_in_transaction(
                    user_id=user_id,
                    amount=self._cost_coins,
                    idempotency_key=idempotency_key,
                    response_body={"operation": "seo_text_generation"},
                )
            except BillingValidationError:
                raise
            except BillingNotFoundError:
                raise
            except BillingError as exc:
                raise SeoTextUpstreamError(str(exc)) from exc

        try:
            content, usage = await self._provider.generate(request)
        except SeoTextConfigurationError:
            await self._safe_refund(user_id=user_id)
            raise
        except Exception:
            await self._safe_refund(user_id=user_id)
            raise

        await self._session.commit()

        if user is not None:
            new_balance = int(user.ai_coins)
        else:
            db_user = await self._session.get(User, user_id)
            new_balance = int(db_user.ai_coins) if db_user is not None else 0

        return SeoTextGenerateResult(
            content=content,
            usage=usage,
            coins_charged=self._cost_coins,
            new_balance=new_balance,
        )

    async def _safe_refund(self, *, user_id: UUID) -> None:
        if self._cost_coins <= 0:
            return
        try:
            await self._billing.refund_coins_in_transaction(
                user_id=user_id,
                amount=self._cost_coins,
            )
        except BillingError:
            logger.exception(
                "Failed to refund seo_text coins for user_id=%s", user_id
            )
