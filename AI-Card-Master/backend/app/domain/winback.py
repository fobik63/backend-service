"""Churn Prevention / Win-back domain: offers, triggers, and Telegram copy."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum
from uuid import UUID


class WinbackTrigger(StrEnum):
    """Why a retention offer was created."""

    CANCEL_INTENT = "cancel_intent"
    INACTIVITY = "inactivity"


class WinbackOfferType(StrEnum):
    """One-shot retention incentive."""

    FREE_GENERATIONS = "free_generations"
    SUBSCRIPTION_DISCOUNT = "subscription_discount"


class WinbackOfferStatus(StrEnum):
    """Lifecycle of a win-back offer."""

    PENDING = "pending"
    CLAIMED = "claimed"
    ACTIVE = "active"
    REDEEMED = "redeemed"
    EXPIRED = "expired"
    DECLINED = "declined"


# Product display name used in Telegram style-update triggers.
LUXURY_LOFT_DISPLAY_NAME = "Luxury Loft"
LUXURY_LOFT_STYLE_KEY = "luxury_loft"

_LUXURY_LOFT_MARKERS = frozenset(
    {
        "luxury loft",
        "luxury_loft",
        "luxury-loft",
        "luxury",
        "loft",
    }
)


@dataclass(frozen=True, slots=True)
class WinbackOfferView:
    """API/domain projection of a retention offer."""

    id: UUID
    user_id: UUID
    trigger: WinbackTrigger
    offer_type: WinbackOfferType
    status: WinbackOfferStatus
    title: str
    message: str
    free_generations: int | None
    discount_percent: int | None
    expires_at: datetime
    claimed_at: datetime | None
    created_at: datetime


@dataclass(frozen=True, slots=True)
class WinbackOfferCopy:
    """Human-readable title and body for an offer type."""

    title: str
    message: str


@dataclass(frozen=True, slots=True)
class InactivityCandidate:
    """User eligible for an inactivity win-back offer."""

    user_id: UUID
    telegram_id: int | None
    last_seen_at: datetime | None
    favorite_style_key: str | None
    favorite_style_display: str


@dataclass(frozen=True, slots=True)
class StyleUpdateRecipient:
    """User who should receive a favorite-style update Telegram."""

    user_id: UUID
    telegram_id: int
    favorite_style_key: str
    favorite_style_display: str


def build_offer_copy(
    offer_type: WinbackOfferType,
    *,
    free_generations: int,
    discount_percent: int,
) -> WinbackOfferCopy:
    """Build localized product copy for a one-shot retention bonus."""

    if offer_type is WinbackOfferType.FREE_GENERATIONS:
        return WinbackOfferCopy(
            title=f"Забери {free_generations} генераций бесплатно",
            message=(
                f"Мы заметили, что ты подумываешь уйти. "
                f"Забери {free_generations} генераций бесплатно — "
                "разовый бонус, действует ограниченное время."
            ),
        )
    return WinbackOfferCopy(
        title=f"Скидка {discount_percent}% на следующий месяц",
        message=(
            f"Оставайся с нами: скидка {discount_percent}% на следующий месяц "
            "подписки. Предложение одноразовое и сгорает после оплаты."
        ),
    )


def pick_offer_type(*, existing_offer_count: int) -> WinbackOfferType:
    """Alternate free generations and discount so users see both incentives."""

    if existing_offer_count % 2 == 0:
        return WinbackOfferType.FREE_GENERATIONS
    return WinbackOfferType.SUBSCRIPTION_DISCOUNT


def compute_discounted_amount(price_rub: Decimal, discount_percent: int) -> Decimal:
    """Apply a percent discount with YooKassa-compatible two-decimal rounding."""

    if discount_percent < 1 or discount_percent > 90:
        raise ValueError("discount_percent must be between 1 and 90.")
    factor = (Decimal(100) - Decimal(discount_percent)) / Decimal(100)
    return (price_rub * factor).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def normalize_style_key(raw: str | None) -> str:
    """Normalize a stored selected_style into a stable key for matching."""

    value = (raw or "").strip().lower().replace("-", " ").replace("_", " ")
    return " ".join(value.split())


def resolve_favorite_style_display(raw_style: str | None) -> str:
    """Map internal style strings to the product display name."""

    normalized = normalize_style_key(raw_style)
    if not normalized:
        return LUXURY_LOFT_DISPLAY_NAME
    if normalized in _LUXURY_LOFT_MARKERS or "luxury" in normalized or "loft" in normalized:
        return LUXURY_LOFT_DISPLAY_NAME
    # Title-case unknown styles for Telegram readability.
    return " ".join(part.capitalize() for part in normalized.split())


def is_luxury_loft_style(raw_style: str | None) -> bool:
    """Whether a selected style should be treated as Luxury Loft."""

    return resolve_favorite_style_display(raw_style) == LUXURY_LOFT_DISPLAY_NAME


def build_style_update_telegram_message(style_display: str) -> str:
    """Trigger copy: favorite style received an update."""

    display = style_display.strip() or LUXURY_LOFT_DISPLAY_NAME
    return (
        f"🎨 Твой любимый стиль «{display}» получил обновление!\n\n"
        "Новые промпты и освещение уже доступны в генераторе. "
        "Зайди и попробуй свежий look на своих карточках."
    )


def build_offer_telegram_message(offer: WinbackOfferView) -> str:
    """Short Telegram nudge for a pending retention offer."""

    return (
        f"{offer.title}\n\n"
        f"{offer.message}\n\n"
        "Открой кабинет → раздел удержания, чтобы забрать бонус."
    )
