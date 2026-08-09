"""Unit tests for Churn Prevention / Win-back domain and service logic."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from app.application.winback_service import (
    WinbackNotFoundError,
    WinbackService,
    WinbackValidationError,
)
from app.domain.winback import (
    LUXURY_LOFT_DISPLAY_NAME,
    WinbackOfferStatus,
    WinbackOfferType,
    WinbackOfferView,
    WinbackTrigger,
    build_offer_copy,
    build_style_update_telegram_message,
    compute_discounted_amount,
    is_luxury_loft_style,
    pick_offer_type,
    resolve_favorite_style_display,
)
from app.models.enums import TariffCode
from app.services.billing_service import expected_tariff_amount
from app.services.tariffs import get_tariff_plan


class _FakeTelegram:
    def __init__(self) -> None:
        self.messages: list[tuple[int, str]] = []

    async def send_message(self, *, chat_id: int, text: str) -> bool:
        self.messages.append((chat_id, text))
        return True


class _FakeWinbackRepo:
    def __init__(self) -> None:
        self.offers: dict[UUID, WinbackOfferView] = {}
        self.balances: dict[UUID, int] = {}
        self.telegram_ids: dict[UUID, int] = {}
        self.last_seen: dict[UUID, datetime] = {}
        self.style_sent: set[tuple[UUID, str, str]] = set()
        self.favorites: dict[UUID, str] = {}
        self.inactivity: list = []

    async def touch_last_seen(self, user_id: UUID, *, now: datetime) -> None:
        self.last_seen[user_id] = now

    async def set_telegram_id(self, user_id: UUID, telegram_id: int) -> None:
        self.telegram_ids[user_id] = telegram_id

    async def get_telegram_id(self, user_id: UUID) -> int | None:
        return self.telegram_ids.get(user_id)

    async def get_active_offer(self, user_id: UUID) -> WinbackOfferView | None:
        now = datetime.now(UTC)
        for offer in self.offers.values():
            if offer.user_id != user_id:
                continue
            if offer.status not in (
                WinbackOfferStatus.PENDING,
                WinbackOfferStatus.ACTIVE,
            ):
                continue
            if offer.expires_at <= now:
                continue
            return offer
        return None

    async def get_offer_for_user(
        self, *, user_id: UUID, offer_id: UUID
    ) -> WinbackOfferView | None:
        offer = self.offers.get(offer_id)
        if offer is None or offer.user_id != user_id:
            return None
        return offer

    async def count_offers(self, user_id: UUID) -> int:
        return sum(1 for offer in self.offers.values() if offer.user_id == user_id)

    async def create_offer(
        self,
        *,
        user_id: UUID,
        trigger: WinbackTrigger,
        offer_type: WinbackOfferType,
        title: str,
        message: str,
        free_generations: int | None,
        discount_percent: int | None,
        expires_at: datetime,
    ) -> WinbackOfferView:
        offer = WinbackOfferView(
            id=uuid4(),
            user_id=user_id,
            trigger=trigger,
            offer_type=offer_type,
            status=WinbackOfferStatus.PENDING,
            title=title,
            message=message,
            free_generations=free_generations,
            discount_percent=discount_percent,
            expires_at=expires_at,
            claimed_at=None,
            created_at=datetime.now(UTC),
        )
        self.offers[offer.id] = offer
        return offer

    async def mark_offer_status(
        self,
        *,
        offer_id: UUID,
        status: WinbackOfferStatus,
        claimed_at: datetime | None = None,
    ) -> WinbackOfferView:
        offer = self.offers[offer_id]
        updated = WinbackOfferView(
            id=offer.id,
            user_id=offer.user_id,
            trigger=offer.trigger,
            offer_type=offer.offer_type,
            status=status,
            title=offer.title,
            message=offer.message,
            free_generations=offer.free_generations,
            discount_percent=offer.discount_percent,
            expires_at=offer.expires_at,
            claimed_at=claimed_at if claimed_at is not None else offer.claimed_at,
            created_at=offer.created_at,
        )
        self.offers[offer_id] = updated
        return updated

    async def credit_free_generations(self, *, user_id: UUID, coins: int) -> int:
        self.balances[user_id] = self.balances.get(user_id, 0) + coins
        return self.balances[user_id]

    async def get_active_discount_percent(self, user_id: UUID) -> int | None:
        offer = await self.get_active_offer(user_id)
        if offer is None or offer.status is not WinbackOfferStatus.ACTIVE:
            return None
        return offer.discount_percent

    async def get_active_discount_offer_id(self, user_id: UUID) -> UUID | None:
        offer = await self.get_active_offer(user_id)
        if offer is None or offer.status is not WinbackOfferStatus.ACTIVE:
            return None
        return offer.id

    async def redeem_discount_offer(self, *, user_id: UUID, offer_id: UUID) -> None:
        await self.mark_offer_status(
            offer_id=offer_id,
            status=WinbackOfferStatus.REDEEMED,
        )

    async def favorite_style_for_user(self, user_id: UUID) -> str | None:
        return self.favorites.get(user_id)

    async def list_inactivity_candidates(self, *, inactive_before: datetime, limit: int):
        return tuple(self.inactivity[:limit])

    async def list_luxury_loft_recipients(self, *, campaign_key: str, limit: int):
        return ()

    async def mark_style_update_sent(
        self, *, user_id: UUID, style_key: str, campaign_key: str
    ) -> None:
        self.style_sent.add((user_id, style_key, campaign_key))

    async def expire_stale_offers(self, *, now: datetime) -> int:
        expired = 0
        for offer_id, offer in list(self.offers.items()):
            if offer.status in (
                WinbackOfferStatus.PENDING,
                WinbackOfferStatus.ACTIVE,
            ) and offer.expires_at <= now:
                await self.mark_offer_status(
                    offer_id=offer_id,
                    status=WinbackOfferStatus.EXPIRED,
                )
                expired += 1
        return expired


def test_pick_offer_type_alternates() -> None:
    assert pick_offer_type(existing_offer_count=0) is WinbackOfferType.FREE_GENERATIONS
    assert pick_offer_type(existing_offer_count=1) is WinbackOfferType.SUBSCRIPTION_DISCOUNT


def test_compute_discounted_amount_and_tariff_helper() -> None:
    plan = get_tariff_plan(TariffCode.PRO)
    discounted = compute_discounted_amount(plan.price_rub, 30)
    assert discounted == Decimal("693.00")
    assert expected_tariff_amount(plan, discount_percent=30) == discounted
    assert expected_tariff_amount(plan) == plan.price_rub


def test_luxury_loft_style_resolution() -> None:
    assert resolve_favorite_style_display("luxury loft apartment") == LUXURY_LOFT_DISPLAY_NAME
    assert is_luxury_loft_style("bright loft")
    assert "Luxury Loft" in build_style_update_telegram_message(LUXURY_LOFT_DISPLAY_NAME)
    copy = build_offer_copy(
        WinbackOfferType.FREE_GENERATIONS,
        free_generations=5,
        discount_percent=30,
    )
    assert "5 генераций" in copy.title


@pytest.mark.asyncio
async def test_cancel_intent_creates_free_generations_offer() -> None:
    repo = _FakeWinbackRepo()
    telegram = _FakeTelegram()
    service = WinbackService(
        repo,
        inactivity_days=10,
        free_generations=5,
        discount_percent=30,
        offer_ttl_hours=72,
        telegram=telegram,
    )
    user_id = uuid4()
    repo.telegram_ids[user_id] = 12345

    offer = await service.register_cancel_intent(user_id)
    assert offer.offer_type is WinbackOfferType.FREE_GENERATIONS
    assert offer.free_generations == 5
    assert offer.status is WinbackOfferStatus.PENDING
    assert telegram.messages
    assert "5 генераций" in telegram.messages[0][1]

    same = await service.register_cancel_intent(user_id)
    assert same.id == offer.id


@pytest.mark.asyncio
async def test_claim_free_generations_and_activate_discount() -> None:
    repo = _FakeWinbackRepo()
    service = WinbackService(
        repo,
        inactivity_days=10,
        free_generations=5,
        discount_percent=30,
        offer_ttl_hours=72,
    )
    user_id = uuid4()
    free_offer = await service.register_cancel_intent(user_id)
    claimed, balance = await service.claim_offer(user_id=user_id, offer_id=free_offer.id)
    assert claimed.status is WinbackOfferStatus.CLAIMED
    assert balance == 5

    # Second offer becomes discount (alternating).
    discount_offer = await service.register_cancel_intent(user_id)
    assert discount_offer.offer_type is WinbackOfferType.SUBSCRIPTION_DISCOUNT
    activated, no_balance = await service.claim_offer(
        user_id=user_id,
        offer_id=discount_offer.id,
    )
    assert activated.status is WinbackOfferStatus.ACTIVE
    assert no_balance is None

    amount, percent, offer_id = await service.resolve_checkout_amount(
        user_id=user_id,
        catalog_price_rub=Decimal("990.00"),
    )
    assert percent == 30
    assert offer_id == discount_offer.id
    assert amount == Decimal("693.00")


@pytest.mark.asyncio
async def test_claim_expired_offer_fails() -> None:
    repo = _FakeWinbackRepo()
    service = WinbackService(
        repo,
        inactivity_days=10,
        free_generations=5,
        discount_percent=30,
        offer_ttl_hours=72,
    )
    user_id = uuid4()
    offer = await service.register_cancel_intent(user_id)
    expired = WinbackOfferView(
        id=offer.id,
        user_id=offer.user_id,
        trigger=offer.trigger,
        offer_type=offer.offer_type,
        status=offer.status,
        title=offer.title,
        message=offer.message,
        free_generations=offer.free_generations,
        discount_percent=offer.discount_percent,
        expires_at=datetime.now(UTC) - timedelta(minutes=1),
        claimed_at=None,
        created_at=offer.created_at,
    )
    repo.offers[offer.id] = expired

    with pytest.raises(WinbackValidationError):
        await service.claim_offer(user_id=user_id, offer_id=offer.id)


@pytest.mark.asyncio
async def test_claim_missing_offer() -> None:
    repo = _FakeWinbackRepo()
    service = WinbackService(
        repo,
        inactivity_days=10,
        free_generations=5,
        discount_percent=30,
        offer_ttl_hours=72,
    )
    with pytest.raises(WinbackNotFoundError):
        await service.claim_offer(user_id=uuid4(), offer_id=uuid4())
