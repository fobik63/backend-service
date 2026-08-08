"""Commercial tariff catalog: prices, durations, and AI-coin grants.

Source of truth for the public tariff grid. Billing services must resolve
tariffs only through this module — never hardcode amounts in routers.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Final, Mapping

from app.models.enums import SubscriptionStatus, TariffCode


@dataclass(frozen=True, slots=True)
class TariffPlan:
    """Immutable definition of one commercial subscription package."""

    code: TariffCode
    title: str
    duration_days: int
    ai_coins: int
    price_rub: Decimal
    subscription_status: SubscriptionStatus
    description: str

    @property
    def amount_value(self) -> str:
        """YooKassa amount string with exactly two decimal places."""

        return f"{self.price_rub:.2f}"


# Strict product tariff grid (1 generation = 1 ИИкоин).
# Public names: Start (free UI) / Pro Lite / Pro / Business.
TARIFF_CATALOG: Final[Mapping[TariffCode, TariffPlan]] = {
    TariffCode.START: TariffPlan(
        code=TariffCode.START,
        title="Pro Lite",
        duration_days=7,
        ai_coins=45,
        price_rub=Decimal("319.00"),
        subscription_status=SubscriptionStatus.START,
        description="Быстрый тест: подписка на 7 дней, 45 ИИкоинов",
    ),
    TariffCode.PRO: TariffPlan(
        code=TariffCode.PRO,
        title="Pro",
        duration_days=30,
        ai_coins=200,
        price_rub=Decimal("990.00"),
        subscription_status=SubscriptionStatus.PRO,
        description="Основной тариф: подписка на 30 дней, 200 ИИкоинов",
    ),
    TariffCode.HALF_YEAR: TariffPlan(
        code=TariffCode.HALF_YEAR,
        title="Business",
        duration_days=180,
        ai_coins=1200,
        price_rub=Decimal("5990.00"),
        subscription_status=SubscriptionStatus.HALF_YEAR,
        description="Масштабирование: подписка на 180 дней, 1200 ИИкоинов",
    ),
    TariffCode.YEAR: TariffPlan(
        code=TariffCode.YEAR,
        title="Business",
        duration_days=365,
        ai_coins=3000,
        price_rub=Decimal("8990.00"),
        subscription_status=SubscriptionStatus.YEAR,
        description="Масштабирование: подписка на 365 дней, 3000 ИИкоинов",
    ),
}


def get_tariff_plan(code: TariffCode | str) -> TariffPlan:
    """Resolve a tariff by code or raise ValueError."""

    if isinstance(code, TariffCode):
        tariff_code = code
    else:
        try:
            tariff_code = TariffCode(str(code).strip().lower())
        except ValueError as exc:
            raise ValueError(f"Unknown tariff code: {code!r}") from exc

    plan = TARIFF_CATALOG.get(tariff_code)
    if plan is None:
        raise ValueError(f"Tariff is not configured: {tariff_code.value}")
    return plan


def list_tariff_plans() -> list[TariffPlan]:
    """Return all commercial tariffs in catalog order."""

    return [
        TARIFF_CATALOG[TariffCode.START],
        TARIFF_CATALOG[TariffCode.PRO],
        TARIFF_CATALOG[TariffCode.HALF_YEAR],
        TARIFF_CATALOG[TariffCode.YEAR],
    ]
