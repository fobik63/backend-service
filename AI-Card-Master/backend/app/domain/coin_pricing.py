"""Volume pricing for standalone AI-coin purchases (no subscription).

Minimum purchase is 50 coins. Ready-made packs are 50 / 250 / 1000 / 5000.
Unit price falls as volume grows so larger packs keep a healthier margin
relative to model cost while remaining cheaper per coin for the buyer.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Final

TWOPLACES: Final[Decimal] = Decimal("0.01")
MIN_PURCHASE_COINS: Final[int] = 50
MAX_PURCHASE_COINS: Final[int] = 5000
COIN_PACKAGES: Final[tuple[int, ...]] = (50, 250, 1000, 5000)

# Highest matching threshold wins. Prices are RUB per coin.
_UNIT_PRICE_TIERS: Final[tuple[tuple[int, Decimal], ...]] = (
    (5000, Decimal("3.90")),
    (1000, Decimal("5.50")),
    (250, Decimal("6.80")),
    (50, Decimal("8.00")),
)


class CoinPricingError(ValueError):
    """Invalid coin quantity or price input."""


@dataclass(frozen=True, slots=True)
class CoinPurchaseQuote:
    """Resolved price for a coin purchase before calling YooKassa."""

    amount_coins: int
    unit_price_rub: Decimal
    amount_rub: Decimal
    currency: str
    package_code: str
    is_preset_package: bool
    description: str
    receipt_item_description: str

    @property
    def amount_value(self) -> str:
        return f"{self.amount_rub:.2f}"


def unit_price_rub_for_coins(amount_coins: int) -> Decimal:
    """Return the volume-discounted unit price for ``amount_coins``."""

    if amount_coins < MIN_PURCHASE_COINS:
        raise CoinPricingError(
            f"Minimum purchase is {MIN_PURCHASE_COINS} AI-coins."
        )
    if amount_coins > MAX_PURCHASE_COINS:
        raise CoinPricingError(
            f"Maximum purchase is {MAX_PURCHASE_COINS} AI-coins."
        )
    for threshold, price in _UNIT_PRICE_TIERS:
        if amount_coins >= threshold:
            return price
    raise CoinPricingError(f"No price tier for {amount_coins} coins.")


def quote_coin_purchase(amount_coins: int) -> CoinPurchaseQuote:
    """Validate quantity and compute the 54-FZ receipt amounts."""

    if not isinstance(amount_coins, int) or isinstance(amount_coins, bool):
        raise CoinPricingError("amount_coins must be an integer.")
    if amount_coins < MIN_PURCHASE_COINS:
        raise CoinPricingError(
            f"Minimum purchase is {MIN_PURCHASE_COINS} AI-coins."
        )
    if amount_coins > MAX_PURCHASE_COINS:
        raise CoinPricingError(
            f"Maximum purchase is {MAX_PURCHASE_COINS} AI-coins."
        )

    unit_price = unit_price_rub_for_coins(amount_coins)
    amount_rub = (unit_price * amount_coins).quantize(
        TWOPLACES, rounding=ROUND_HALF_UP
    )
    is_preset = amount_coins in COIN_PACKAGES
    package_code = str(amount_coins) if is_preset else "custom"
    pack_label = (
        f"пакет {amount_coins}" if is_preset else f"произвольное количество {amount_coins}"
    )
    description = (
        f"AI-Card-Master — покупка {amount_coins} ИИ-коинов ({pack_label}) "
        "для аналитики и генерации карточек Wildberries/Ozon"
    )
    receipt_item = (
        f"ИИ-коины AI-Card-Master, {amount_coins} шт. "
        f"({pack_label}). Цифровой сервис: генерация и аналитика карточек "
        "товаров Wildberries/Ozon."
    )[:128]
    return CoinPurchaseQuote(
        amount_coins=amount_coins,
        unit_price_rub=unit_price,
        amount_rub=amount_rub,
        currency="RUB",
        package_code=package_code,
        is_preset_package=is_preset,
        description=description,
        receipt_item_description=receipt_item,
    )


def list_coin_packages() -> list[CoinPurchaseQuote]:
    """Ready-made packs shown on the billing page."""

    return [quote_coin_purchase(size) for size in COIN_PACKAGES]
