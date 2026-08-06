"""Application use cases for Churn Prevention / Win-back."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

from app.application.ports.winback import WinbackPersistencePort
from app.domain.winback import (
    LUXURY_LOFT_DISPLAY_NAME,
    LUXURY_LOFT_STYLE_KEY,
    WinbackOfferStatus,
    WinbackOfferType,
    WinbackOfferView,
    WinbackTrigger,
    build_offer_copy,
    build_offer_telegram_message,
    build_style_update_telegram_message,
    compute_discounted_amount,
    pick_offer_type,
)


class WinbackError(Exception):
    """Base win-back workflow failure."""


class WinbackValidationError(WinbackError):
    """Request is invalid for the current user/offer state."""


class WinbackNotFoundError(WinbackError):
    """Offer or user resource was not found."""


class TelegramUserNotifierPort:
    """Protocol-like duck type for sending user-facing Telegram messages."""

    async def send_message(self, *, chat_id: int, text: str) -> bool:
        """Return True when Telegram accepted the message."""

        raise NotImplementedError


class WinbackService:
    """Coordinate churn triggers, one-shot offers, and style-update Telegram."""

    def __init__(
        self,
        repository: WinbackPersistencePort,
        *,
        inactivity_days: int,
        free_generations: int,
        discount_percent: int,
        offer_ttl_hours: int,
        telegram: TelegramUserNotifierPort | None = None,
    ) -> None:
        if inactivity_days <= 0:
            raise WinbackValidationError("inactivity_days must be positive.")
        if free_generations <= 0:
            raise WinbackValidationError("free_generations must be positive.")
        if discount_percent < 1 or discount_percent > 90:
            raise WinbackValidationError("discount_percent must be between 1 and 90.")
        if offer_ttl_hours <= 0:
            raise WinbackValidationError("offer_ttl_hours must be positive.")
        self._repository = repository
        self._inactivity_days = inactivity_days
        self._free_generations = free_generations
        self._discount_percent = discount_percent
        self._offer_ttl_hours = offer_ttl_hours
        self._telegram = telegram

    async def touch_last_seen(self, user_id: UUID) -> None:
        """Record product activity used by the inactivity scanner."""

        await self._repository.touch_last_seen(user_id, now=datetime.now(UTC))

    async def link_telegram(self, *, user_id: UUID, telegram_id: int) -> None:
        """Attach Telegram chat id for trigger messages."""

        if telegram_id == 0:
            raise WinbackValidationError("telegram_id must be a non-zero chat id.")
        try:
            await self._repository.set_telegram_id(user_id, telegram_id)
        except ValueError as exc:
            raise WinbackValidationError(str(exc)) from exc

    async def get_current_offer(self, user_id: UUID) -> WinbackOfferView | None:
        """Return the user's open retention offer, if any."""

        await self._repository.expire_stale_offers(now=datetime.now(UTC))
        return await self._repository.get_active_offer(user_id)

    async def register_cancel_intent(self, user_id: UUID) -> WinbackOfferView:
        """Create (or return) a one-shot offer when the cancel page is opened."""

        return await self._ensure_offer(
            user_id=user_id,
            trigger=WinbackTrigger.CANCEL_INTENT,
            notify_telegram=True,
        )

    async def claim_offer(
        self, *, user_id: UUID, offer_id: UUID
    ) -> tuple[WinbackOfferView, int | None]:
        """Claim free generations or activate a subscription discount.

        Returns (offer, new_ai_coin_balance_or_none).
        """

        await self._repository.expire_stale_offers(now=datetime.now(UTC))
        offer = await self._repository.get_offer_for_user(
            user_id=user_id, offer_id=offer_id
        )
        if offer is None:
            raise WinbackNotFoundError("Win-back offer not found.")
        if offer.status is not WinbackOfferStatus.PENDING:
            raise WinbackValidationError("Offer is not available to claim.")
        if offer.expires_at <= datetime.now(UTC):
            await self._repository.mark_offer_status(
                offer_id=offer.id,
                status=WinbackOfferStatus.EXPIRED,
            )
            raise WinbackValidationError("Offer has expired.")

        now = datetime.now(UTC)
        if offer.offer_type is WinbackOfferType.FREE_GENERATIONS:
            coins = int(offer.free_generations or self._free_generations)
            new_balance = await self._repository.credit_free_generations(
                user_id=user_id,
                coins=coins,
            )
            updated = await self._repository.mark_offer_status(
                offer_id=offer.id,
                status=WinbackOfferStatus.CLAIMED,
                claimed_at=now,
            )
            return updated, new_balance

        updated = await self._repository.mark_offer_status(
            offer_id=offer.id,
            status=WinbackOfferStatus.ACTIVE,
            claimed_at=now,
        )
        return updated, None

    async def resolve_checkout_amount(
        self, *, user_id: UUID, catalog_price_rub: Decimal
    ) -> tuple[Decimal, int | None, UUID | None]:
        """Return (amount, discount_percent, offer_id) for YooKassa checkout."""

        await self._repository.expire_stale_offers(now=datetime.now(UTC))
        offer_id = await self._repository.get_active_discount_offer_id(user_id)
        percent = await self._repository.get_active_discount_percent(user_id)
        if offer_id is None or percent is None:
            return catalog_price_rub, None, None
        discounted = compute_discounted_amount(catalog_price_rub, percent)
        return discounted, percent, offer_id

    async def redeem_discount_after_payment(
        self, *, user_id: UUID, offer_id: UUID | None
    ) -> None:
        """Consume an ACTIVE discount once payment succeeds."""

        if offer_id is None:
            return
        await self._repository.redeem_discount_offer(user_id=user_id, offer_id=offer_id)

    async def process_inactivity_batch(self, *, limit: int = 100) -> dict[str, int]:
        """Create inactivity offers and optionally notify via Telegram."""

        now = datetime.now(UTC)
        expired = await self._repository.expire_stale_offers(now=now)
        inactive_before = now - timedelta(days=self._inactivity_days)
        candidates = await self._repository.list_inactivity_candidates(
            inactive_before=inactive_before,
            limit=limit,
        )
        created = 0
        notified = 0
        for candidate in candidates:
            offer = await self._ensure_offer(
                user_id=candidate.user_id,
                trigger=WinbackTrigger.INACTIVITY,
                notify_telegram=False,
            )
            created += 1
            if candidate.telegram_id is not None and await self._send_telegram(
                chat_id=candidate.telegram_id,
                text=build_offer_telegram_message(offer),
            ):
                notified += 1
            # Style-update nudge for Luxury Loft fans who went dormant.
            if (
                candidate.telegram_id is not None
                and candidate.favorite_style_display == LUXURY_LOFT_DISPLAY_NAME
            ):
                await self._send_telegram(
                    chat_id=candidate.telegram_id,
                    text=build_style_update_telegram_message(
                        candidate.favorite_style_display
                    ),
                )
        return {
            "expired_offers": expired,
            "offers_created": created,
            "telegram_notified": notified,
            "candidates": len(candidates),
        }

    async def notify_luxury_loft_updates(
        self,
        *,
        campaign_key: str,
        limit: int = 200,
    ) -> dict[str, int]:
        """Send style-update Telegrams to Luxury Loft fans (idempotent per campaign)."""

        recipients = await self._repository.list_luxury_loft_recipients(
            campaign_key=campaign_key,
            limit=limit,
        )
        sent = 0
        for recipient in recipients:
            text = build_style_update_telegram_message(recipient.favorite_style_display)
            ok = await self._send_telegram(chat_id=recipient.telegram_id, text=text)
            if not ok:
                continue
            await self._repository.mark_style_update_sent(
                user_id=recipient.user_id,
                style_key=LUXURY_LOFT_STYLE_KEY,
                campaign_key=campaign_key,
            )
            sent += 1
        return {"recipients": len(recipients), "sent": sent}

    async def _ensure_offer(
        self,
        *,
        user_id: UUID,
        trigger: WinbackTrigger,
        notify_telegram: bool,
    ) -> WinbackOfferView:
        await self._repository.expire_stale_offers(now=datetime.now(UTC))
        existing = await self._repository.get_active_offer(user_id)
        if existing is not None:
            return existing

        offer_type = pick_offer_type(
            existing_offer_count=await self._repository.count_offers(user_id)
        )
        free_gens: int | None = None
        discount: int | None = None
        if offer_type is WinbackOfferType.FREE_GENERATIONS:
            free_gens = self._free_generations
        else:
            discount = self._discount_percent
        copy = build_offer_copy(
            offer_type,
            free_generations=self._free_generations,
            discount_percent=self._discount_percent,
        )
        offer = await self._repository.create_offer(
            user_id=user_id,
            trigger=trigger,
            offer_type=offer_type,
            title=copy.title,
            message=copy.message,
            free_generations=free_gens,
            discount_percent=discount,
            expires_at=datetime.now(UTC) + timedelta(hours=self._offer_ttl_hours),
        )
        if notify_telegram:
            chat_id = await self._repository.get_telegram_id(user_id)
            if chat_id is not None:
                await self._send_telegram(
                    chat_id=chat_id,
                    text=build_offer_telegram_message(offer),
                )
        return offer

    async def _send_telegram(self, *, chat_id: int, text: str) -> bool:
        if self._telegram is None:
            return False
        return await self._telegram.send_message(chat_id=chat_id, text=text)
