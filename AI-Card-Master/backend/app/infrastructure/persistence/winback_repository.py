"""SQLAlchemy adapter for Churn Prevention / Win-back persistence."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.winback import (
    LUXURY_LOFT_STYLE_KEY,
    InactivityCandidate,
    StyleUpdateRecipient,
    WinbackOfferStatus,
    WinbackOfferType,
    WinbackOfferView,
    WinbackTrigger,
    is_luxury_loft_style,
    resolve_favorite_style_display,
)
from app.models.style_preset_selection import StylePresetSelection
from app.models.user import User
from app.models.winback import WinbackOffer, WinbackStyleNotification


def _to_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _to_view(row: WinbackOffer) -> WinbackOfferView:
    return WinbackOfferView(
        id=row.id,
        user_id=row.user_id,
        trigger=WinbackTrigger(row.trigger),
        offer_type=WinbackOfferType(row.offer_type),
        status=WinbackOfferStatus(row.status),
        title=row.title,
        message=row.message,
        free_generations=row.free_generations,
        discount_percent=row.discount_percent,
        expires_at=_to_utc(row.expires_at),
        claimed_at=_to_utc(row.claimed_at) if row.claimed_at is not None else None,
        created_at=_to_utc(row.created_at),
    )


class WinbackRepository:
    """Persist win-back offers, activity signals, and Telegram notify logs."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def touch_last_seen(self, user_id: UUID, *, now: datetime) -> None:
        """Update last_seen_at when the user is active in the product."""

        user = await self._session.get(User, user_id)
        if user is None:
            return
        previous = _to_utc(user.last_seen_at) if user.last_seen_at is not None else None
        # Throttle writes: skip if updated within the last hour.
        if previous is not None and (now - previous).total_seconds() < 3600:
            return
        user.last_seen_at = now
        await self._session.commit()

    async def set_telegram_id(self, user_id: UUID, telegram_id: int) -> None:
        """Bind a Telegram chat id used for trigger messages."""

        user = await self._session.get(User, user_id, with_for_update=True)
        if user is None:
            raise ValueError(f"User {user_id} not found.")
        conflict = await self._session.scalar(
            select(User.id).where(
                User.telegram_id == telegram_id,
                User.id != user_id,
            )
        )
        if conflict is not None:
            raise ValueError("Telegram id is already linked to another account.")
        user.telegram_id = telegram_id
        await self._session.commit()

    async def get_telegram_id(self, user_id: UUID) -> int | None:
        """Return linked Telegram chat id, if any."""

        return await self._session.scalar(
            select(User.telegram_id).where(User.id == user_id)
        )

    async def get_active_offer(self, user_id: UUID) -> WinbackOfferView | None:
        """Return pending or active (unused discount) offer that is not expired."""

        now = datetime.now(UTC)
        row = await self._session.scalar(
            select(WinbackOffer)
            .where(
                WinbackOffer.user_id == user_id,
                WinbackOffer.status.in_(
                    (
                        WinbackOfferStatus.PENDING.value,
                        WinbackOfferStatus.ACTIVE.value,
                    )
                ),
                WinbackOffer.expires_at > now,
            )
            .order_by(WinbackOffer.created_at.desc())
            .limit(1)
        )
        return _to_view(row) if row is not None else None

    async def get_offer_for_user(
        self, *, user_id: UUID, offer_id: UUID
    ) -> WinbackOfferView | None:
        """Load one offer owned by the user."""

        row = await self._session.scalar(
            select(WinbackOffer).where(
                WinbackOffer.id == offer_id,
                WinbackOffer.user_id == user_id,
            )
        )
        return _to_view(row) if row is not None else None

    async def count_offers(self, user_id: UUID) -> int:
        """Total offers ever created for alternating offer-type selection."""

        count = await self._session.scalar(
            select(func.count())
            .select_from(WinbackOffer)
            .where(WinbackOffer.user_id == user_id)
        )
        return int(count or 0)

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
        """Persist a new one-shot retention offer."""

        row = WinbackOffer(
            user_id=user_id,
            trigger=trigger.value,
            offer_type=offer_type.value,
            status=WinbackOfferStatus.PENDING.value,
            title=title,
            message=message,
            free_generations=free_generations,
            discount_percent=discount_percent,
            expires_at=expires_at,
        )
        self._session.add(row)
        await self._session.commit()
        await self._session.refresh(row)
        return _to_view(row)

    async def mark_offer_status(
        self,
        *,
        offer_id: UUID,
        status: WinbackOfferStatus,
        claimed_at: datetime | None = None,
    ) -> WinbackOfferView:
        """Transition offer lifecycle status."""

        row = await self._session.get(WinbackOffer, offer_id, with_for_update=True)
        if row is None:
            raise ValueError(f"Offer {offer_id} not found.")
        row.status = status.value
        if claimed_at is not None:
            row.claimed_at = claimed_at
        await self._session.commit()
        await self._session.refresh(row)
        return _to_view(row)

    async def credit_free_generations(self, *, user_id: UUID, coins: int) -> int:
        """Add AI-coins and return the new balance."""

        if coins <= 0:
            raise ValueError("coins must be positive.")
        from app.services.billing_service import BillingNotFoundError, BillingService

        try:
            # Single write-path: BillingService.in_transaction (audit R1).
            user = await BillingService(self._session).credit_coins_in_transaction(
                user_id=user_id, amount=int(coins)
            )
        except BillingNotFoundError as exc:
            raise ValueError(f"User {user_id} not found.") from exc
        await self._session.commit()
        await self._session.refresh(user)
        return int(user.ai_coins)

    async def get_active_discount_percent(self, user_id: UUID) -> int | None:
        """Return discount percent for an ACTIVE subscription_discount offer."""

        now = datetime.now(UTC)
        percent = await self._session.scalar(
            select(WinbackOffer.discount_percent)
            .where(
                WinbackOffer.user_id == user_id,
                WinbackOffer.offer_type
                == WinbackOfferType.SUBSCRIPTION_DISCOUNT.value,
                WinbackOffer.status == WinbackOfferStatus.ACTIVE.value,
                WinbackOffer.expires_at > now,
            )
            .order_by(WinbackOffer.created_at.desc())
            .limit(1)
        )
        return int(percent) if percent is not None else None

    async def get_active_discount_offer_id(self, user_id: UUID) -> UUID | None:
        """Return ACTIVE discount offer id for payment redemption."""

        now = datetime.now(UTC)
        return await self._session.scalar(
            select(WinbackOffer.id)
            .where(
                WinbackOffer.user_id == user_id,
                WinbackOffer.offer_type
                == WinbackOfferType.SUBSCRIPTION_DISCOUNT.value,
                WinbackOffer.status == WinbackOfferStatus.ACTIVE.value,
                WinbackOffer.expires_at > now,
            )
            .order_by(WinbackOffer.created_at.desc())
            .limit(1)
        )

    async def redeem_discount_offer(self, *, user_id: UUID, offer_id: UUID) -> None:
        """Mark an ACTIVE discount offer as REDEEMED after successful payment."""

        row = await self._session.get(WinbackOffer, offer_id, with_for_update=True)
        if row is None or row.user_id != user_id:
            return
        if row.status != WinbackOfferStatus.ACTIVE.value:
            return
        row.status = WinbackOfferStatus.REDEEMED.value
        await self._session.commit()

    async def favorite_style_for_user(self, user_id: UUID) -> str | None:
        """Most frequently selected style for the user, if any."""

        row = await self._session.execute(
            select(
                StylePresetSelection.selected_style,
                func.count().label("cnt"),
            )
            .where(StylePresetSelection.user_id == user_id)
            .group_by(StylePresetSelection.selected_style)
            .order_by(func.count().desc())
            .limit(1)
        )
        first = row.first()
        if first is None:
            return None
        return str(first[0])

    async def list_inactivity_candidates(
        self,
        *,
        inactive_before: datetime,
        limit: int,
    ) -> tuple[InactivityCandidate, ...]:
        """Users inactive long enough and without a usable open offer."""

        now = datetime.now(UTC)
        open_offer_exists = (
            select(WinbackOffer.id)
            .where(
                WinbackOffer.user_id == User.id,
                WinbackOffer.status.in_(
                    (
                        WinbackOfferStatus.PENDING.value,
                        WinbackOfferStatus.ACTIVE.value,
                    )
                ),
                WinbackOffer.expires_at > now,
            )
            .exists()
        )
        result = await self._session.execute(
            select(User)
            .where(
                User.is_banned.is_(False),
                ~open_offer_exists,
                or_(
                    and_(
                        User.last_seen_at.is_not(None),
                        User.last_seen_at < inactive_before,
                    ),
                    and_(
                        User.last_seen_at.is_(None),
                        User.created_at < inactive_before,
                    ),
                ),
            )
            .order_by(User.created_at.asc())
            .limit(limit)
        )
        users = result.scalars().all()
        candidates: list[InactivityCandidate] = []
        for user in users:
            favorite = await self.favorite_style_for_user(user.id)
            candidates.append(
                InactivityCandidate(
                    user_id=user.id,
                    telegram_id=user.telegram_id,
                    last_seen_at=_to_utc(user.last_seen_at)
                    if user.last_seen_at is not None
                    else None,
                    favorite_style_key=favorite,
                    favorite_style_display=resolve_favorite_style_display(favorite),
                )
            )
        return tuple(candidates)

    async def list_luxury_loft_recipients(
        self,
        *,
        campaign_key: str,
        limit: int,
    ) -> tuple[StyleUpdateRecipient, ...]:
        """Users whose favorite style is Luxury Loft and not yet notified."""

        already_sent = (
            select(WinbackStyleNotification.id)
            .where(
                WinbackStyleNotification.user_id == User.id,
                WinbackStyleNotification.style_key == LUXURY_LOFT_STYLE_KEY,
                WinbackStyleNotification.campaign_key == campaign_key,
            )
            .exists()
        )
        result = await self._session.execute(
            select(User)
            .where(
                User.is_banned.is_(False),
                User.telegram_id.is_not(None),
                ~already_sent,
            )
            .order_by(User.created_at.asc())
            .limit(limit * 5)
        )
        recipients: list[StyleUpdateRecipient] = []
        for user in result.scalars().all():
            favorite = await self.favorite_style_for_user(user.id)
            if favorite is None or not is_luxury_loft_style(favorite):
                # Also include users with no history as Luxury Loft fans
                # only when they explicitly selected it — skip empty history.
                continue
            if user.telegram_id is None:
                continue
            recipients.append(
                StyleUpdateRecipient(
                    user_id=user.id,
                    telegram_id=int(user.telegram_id),
                    favorite_style_key=LUXURY_LOFT_STYLE_KEY,
                    favorite_style_display=resolve_favorite_style_display(favorite),
                )
            )
            if len(recipients) >= limit:
                break
        return tuple(recipients)

    async def mark_style_update_sent(
        self,
        *,
        user_id: UUID,
        style_key: str,
        campaign_key: str,
    ) -> None:
        """Record that a style-update Telegram was delivered."""

        self._session.add(
            WinbackStyleNotification(
                user_id=user_id,
                style_key=style_key,
                campaign_key=campaign_key,
            )
        )
        await self._session.commit()

    async def expire_stale_offers(self, *, now: datetime) -> int:
        """Flip PENDING/ACTIVE offers past expires_at to EXPIRED."""

        result = await self._session.execute(
            select(WinbackOffer).where(
                WinbackOffer.status.in_(
                    (
                        WinbackOfferStatus.PENDING.value,
                        WinbackOfferStatus.ACTIVE.value,
                    )
                ),
                WinbackOffer.expires_at <= now,
            )
        )
        rows = result.scalars().all()
        for row in rows:
            row.status = WinbackOfferStatus.EXPIRED.value
        if rows:
            await self._session.commit()
        return len(rows)
