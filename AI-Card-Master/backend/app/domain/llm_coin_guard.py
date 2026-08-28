"""Pricing and 402 payload for LLM SEO / review generation coin spends."""

from __future__ import annotations

import hashlib
from enum import StrEnum
from typing import Any, Final, Mapping

from app.domain.coin_pricing import MIN_PURCHASE_COINS

_IDEMPOTENCY_KEY_MAX_LEN: Final[int] = 255


def bind_idempotency_key(*, user_id: object, route: str, body: bytes | str) -> str:
    """Bind a ledger/HTTP key to ``user_id + route + sha256(body)``.

    A payload change yields a new key, so a reused ``X-Idempotency-Key``
    cannot replay a cheaper debit onto a different LLM prompt.
    """

    payload = body if isinstance(body, bytes) else body.encode("utf-8")
    digest = hashlib.sha256(payload).hexdigest()
    raw = f"{user_id}:{route}:{digest}"
    if len(raw) <= _IDEMPOTENCY_KEY_MAX_LEN:
        return raw
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


SEO_CARD_COST_COINS: Final[int] = 2
REVIEW_COST_COINS: Final[int] = 2

INSUFFICIENT_COINS_MESSAGE: Final[str] = (
    "Недостаточно коинов. Минимальный пакет для докупки — "
    f"{MIN_PURCHASE_COINS} коинов"
)
PAYMENT_MODAL_ID: Final[str] = "buy_coins"
PAYMENT_MODAL_HREF: Final[str] = "/dashboard?modal=buy_coins"
BATCH_STOP_INSUFFICIENT: Final[str] = "insufficient_coins"


class LlmCoinOperation(StrEnum):
    """Billable LLM artifact for marketplace cards."""

    SEO_CARD = "seo_card"
    REVIEW = "review"


LLM_OPERATION_COSTS: Final[Mapping[LlmCoinOperation, int]] = {
    LlmCoinOperation.SEO_CARD: SEO_CARD_COST_COINS,
    LlmCoinOperation.REVIEW: REVIEW_COST_COINS,
}


def unit_cost_coins(operation: LlmCoinOperation) -> int:
    """Return the coin price of a single LLM generation unit."""

    return int(LLM_OPERATION_COSTS[operation])


def required_coins_for(operation: LlmCoinOperation, *, quantity: int) -> int:
    """Return the full pre-start cost for ``quantity`` units of ``operation``."""

    if quantity < 1:
        raise ValueError("quantity must be >= 1.")
    return unit_cost_coins(operation) * int(quantity)


def insufficient_coins_http_detail(
    *,
    required_coins: int,
    balance: int,
) -> dict[str, Any]:
    """Structured FastAPI ``detail`` for HTTP 402 Payment Required."""

    return {
        "code": "insufficient_coins",
        "message": INSUFFICIENT_COINS_MESSAGE,
        "payment_modal": PAYMENT_MODAL_ID,
        "payment_modal_href": PAYMENT_MODAL_HREF,
        "min_pack_coins": MIN_PURCHASE_COINS,
        "required_coins": int(required_coins),
        "balance": int(balance),
    }


class InsufficientCoinsError(Exception):
    """Raised when the wallet cannot cover the next LLM unit (HTTP 402)."""

    status_code: int = 402
    code: str = "insufficient_coins"

    def __init__(
        self,
        *,
        required_coins: int,
        balance: int,
    ) -> None:
        self.required_coins = int(required_coins)
        self.balance = int(balance)
        self.message = INSUFFICIENT_COINS_MESSAGE
        super().__init__(self.message)

    def to_http_detail(self) -> dict[str, Any]:
        return insufficient_coins_http_detail(
            required_coins=self.required_coins,
            balance=self.balance,
        )
