"""Use case: generate WB/Ozon SEO copy and debit AI-coins (Safe Spend)."""

from __future__ import annotations

import logging
from typing import Any, Final
from uuid import UUID

from app.application.llm_coin_guard import LlmCoinGuard
from app.application.ports.seo_text import SeoTextProviderPort
from app.core.config import get_settings
from app.domain.llm_coin_guard import SEO_CARD_COST_COINS, LlmCoinOperation, bind_idempotency_key
from app.domain.seo_text import (
    SeoTextBatchGenerateResult,
    SeoTextContent,
    SeoTextGenerateRequest,
    SeoTextGenerateResult,
    SeoTextUpstreamError,
    SeoTextValidationError,
    SeoTokenUsage,
)
from app.models.user import User
from app.services.billing_service import (
    BillingError,
    BillingNotFoundError,
    BillingService,
    BillingValidationError,
)

logger = logging.getLogger(__name__)

SEO_TEXT_COST_COINS: Final[int] = SEO_CARD_COST_COINS
_SEO_ROUTE: Final[str] = "/api/ai/generate-description"


def _dump_seo_llm(content: SeoTextContent, usage: SeoTokenUsage) -> dict[str, Any]:
    return {
        "content": content.model_dump(mode="json"),
        "usage": usage.model_dump(mode="json"),
    }


def _load_seo_llm(raw: Any) -> tuple[SeoTextContent, SeoTokenUsage]:
    if isinstance(raw, tuple) and len(raw) == 2:
        content, usage = raw
        if isinstance(content, SeoTextContent) and isinstance(usage, SeoTokenUsage):
            return content, usage
    if not isinstance(raw, dict):
        raise SeoTextUpstreamError("Cached SEO payload is unusable.")
    return (
        SeoTextContent.model_validate(raw["content"]),
        SeoTokenUsage.model_validate(raw["usage"]),
    )


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
        self._coin_guard = LlmCoinGuard(
            session,
            billing=self._billing,
            charge_coins=self._charge_coins,
        )

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

        ledger_key = bind_idempotency_key(
            user_id=user_id,
            route=_SEO_ROUTE,
            body=request.model_dump_json(),
        )

        async def llm_call() -> dict[str, Any]:
            content, usage = await self._provider.generate(request)
            return _dump_seo_llm(content, usage)

        try:
            raw, user, charged = await self._coin_guard.predebit_then_call(
                user_id=user_id,
                operation=LlmCoinOperation.SEO_CARD,
                quantity=1,
                idempotency_key=ledger_key,
                llm_call=llm_call,
            )
        except BillingValidationError:
            raise
        except BillingNotFoundError:
            raise
        except BillingError as exc:
            raise SeoTextUpstreamError(str(exc)) from exc

        content, usage = _load_seo_llm(raw)

        await self._session.commit()

        if user is not None:
            new_balance = int(user.ai_coins)
        else:
            db_user = await self._session.get(User, user_id)
            new_balance = int(db_user.ai_coins) if db_user is not None else 0

        return SeoTextGenerateResult(
            content=content,
            usage=usage,
            coins_charged=charged,
            new_balance=new_balance,
        )

    async def generate_batch(
        self,
        *,
        user_id: UUID,
        requests: tuple[SeoTextGenerateRequest, ...] | list[SeoTextGenerateRequest],
        idempotency_key: str | None = None,
    ) -> SeoTextBatchGenerateResult:
        """Generate many SEO cards; debit 2 coins per card until the wallet is empty."""

        items = tuple(requests)
        for request in items:
            if not request.title.strip():
                raise SeoTextValidationError("title must not be empty.")
            if not request.category.strip():
                raise SeoTextValidationError("category must not be empty.")

        ensure = getattr(self._provider, "ensure_configured", None)
        if callable(ensure):
            ensure()

        async def generate_one(item: SeoTextGenerateRequest) -> dict[str, Any]:
            content, usage = await self._provider.generate(item)
            return _dump_seo_llm(content, usage)

        try:
            batch = await self._coin_guard.run_batch(
                user_id=user_id,
                operation=LlmCoinOperation.SEO_CARD,
                items=items,
                generate_one=generate_one,
                persist=self._session.commit,
                idempotency_key=idempotency_key,
            )
        except BillingValidationError:
            raise
        except BillingNotFoundError:
            raise
        except BillingError as exc:
            raise SeoTextUpstreamError(str(exc)) from exc

        unit = self._coin_guard.cost_for(LlmCoinOperation.SEO_CARD, quantity=1)
        results = tuple(
            SeoTextGenerateResult(
                content=content,
                usage=usage,
                coins_charged=unit,
                new_balance=batch.new_balance,
            )
            for content, usage in (_load_seo_llm(raw) for raw in batch.items)
        )
        if batch.stopped_reason:
            logger.info(
                "SEO batch stopped user_id=%s reason=%s generated=%s skipped=%s",
                user_id,
                batch.stopped_reason,
                len(results),
                batch.skipped_count,
            )
        return SeoTextBatchGenerateResult(
            items=results,
            coins_charged=batch.coins_charged,
            new_balance=batch.new_balance,
            skipped_count=batch.skipped_count,
            stopped_reason=batch.stopped_reason,
        )

    async def _safe_refund(self, *, user_id: UUID) -> None:
        if self._cost_coins <= 0:
            return
        await self._coin_guard.refund(user_id=user_id, amount=self._cost_coins)
