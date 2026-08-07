"""SQLAlchemy adapter for Custom Brand LoRA persistence."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.domain.brand_lora import (
    BrandLoraReferenceView,
    BrandLoraStatus,
    BrandLoraView,
    BrandStyleFilter,
)
from app.models.brand_lora import BrandLoraProfile, BrandLoraReference
from app.models.user import User
from app.services.billing_service import BillingValidationError


def _to_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _ref_view(row: BrandLoraReference) -> BrandLoraReferenceView:
    return BrandLoraReferenceView(
        id=row.id,
        profile_id=row.profile_id,
        position=row.position,
        object_key=row.object_key,
        mime_type=row.mime_type,
        size_bytes=row.size_bytes,
        created_at=_to_utc(row.created_at),
    )


def _profile_view(
    row: BrandLoraProfile, *, include_references: bool
) -> BrandLoraView:
    refs: tuple[BrandLoraReferenceView, ...] = ()
    if include_references and row.references is not None:
        refs = tuple(_ref_view(item) for item in row.references)
    return BrandLoraView(
        id=row.id,
        user_id=row.user_id,
        name=row.name,
        trigger_word=row.trigger_word,
        status=BrandLoraStatus(row.status),
        is_active=bool(row.is_active),
        brand_style_prompt=row.brand_style_prompt,
        lora_weights_url=row.lora_weights_url,
        provider_training_id=row.provider_training_id,
        provider_version_id=row.provider_version_id,
        lora_scale=float(row.lora_scale),
        reference_count=int(row.reference_count),
        coins_charged=int(row.coins_charged),
        error_message=row.error_message,
        training_progress=int(row.training_progress),
        notes=row.notes,
        created_at=_to_utc(row.created_at),
        updated_at=_to_utc(row.updated_at),
        trained_at=_to_utc(row.trained_at) if row.trained_at is not None else None,
        references=refs,
    )


class BrandLoraRepository:
    """Persist brand LoRA profiles, references, and activation state."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_profile(
        self,
        *,
        user_id: UUID,
        name: str,
        trigger_word: str,
        notes: str | None,
        coins_charged: int,
        references: tuple[tuple[str, str, int], ...],
    ) -> BrandLoraView:
        now = datetime.now(UTC)
        if coins_charged > 0:
            await self.debit_coins(user_id=user_id, amount=coins_charged)
        profile = BrandLoraProfile(
            user_id=user_id,
            name=name,
            trigger_word=trigger_word,
            status=BrandLoraStatus.QUEUED.value,
            is_active=False,
            notes=notes,
            coins_charged=coins_charged,
            reference_count=len(references),
            training_progress=0,
            created_at=now,
            updated_at=now,
        )
        self._session.add(profile)
        await self._session.flush()
        for position, (object_key, mime_type, size_bytes) in enumerate(
            references, start=1
        ):
            self._session.add(
                BrandLoraReference(
                    profile_id=profile.id,
                    position=position,
                    object_key=object_key,
                    mime_type=mime_type,
                    size_bytes=size_bytes,
                    created_at=now,
                )
            )
        await self._session.commit()
        loaded = await self.get(profile_id=profile.id, include_references=True)
        if loaded is None:
            raise LookupError("Brand LoRA profile disappeared after create.")
        return loaded

    async def get_for_user(
        self, *, user_id: UUID, profile_id: UUID, include_references: bool = False
    ) -> BrandLoraView | None:
        stmt = select(BrandLoraProfile).where(
            BrandLoraProfile.id == profile_id,
            BrandLoraProfile.user_id == user_id,
        )
        if include_references:
            stmt = stmt.options(selectinload(BrandLoraProfile.references))
        row = await self._session.scalar(stmt)
        if row is None:
            return None
        return _profile_view(row, include_references=include_references)

    async def get(
        self, *, profile_id: UUID, include_references: bool = True
    ) -> BrandLoraView | None:
        stmt = select(BrandLoraProfile).where(BrandLoraProfile.id == profile_id)
        if include_references:
            stmt = stmt.options(selectinload(BrandLoraProfile.references))
        row = await self._session.scalar(stmt)
        if row is None:
            return None
        return _profile_view(row, include_references=include_references)

    async def list_for_user(
        self, *, user_id: UUID, limit: int = 50
    ) -> tuple[BrandLoraView, ...]:
        rows = (
            await self._session.scalars(
                select(BrandLoraProfile)
                .where(
                    BrandLoraProfile.user_id == user_id,
                    BrandLoraProfile.status != BrandLoraStatus.ARCHIVED.value,
                )
                .order_by(BrandLoraProfile.created_at.desc())
                .limit(max(1, min(limit, 100)))
            )
        ).all()
        return tuple(_profile_view(row, include_references=False) for row in rows)

    async def get_active_filter(self, *, user_id: UUID) -> BrandStyleFilter | None:
        row = await self._session.scalar(
            select(BrandLoraProfile).where(
                BrandLoraProfile.user_id == user_id,
                BrandLoraProfile.is_active.is_(True),
                BrandLoraProfile.status == BrandLoraStatus.READY.value,
            )
        )
        if row is None or not row.brand_style_prompt:
            return None
        return BrandStyleFilter(
            profile_id=row.id,
            trigger_word=row.trigger_word,
            brand_style_prompt=row.brand_style_prompt,
            lora_weights_url=row.lora_weights_url,
            lora_scale=float(row.lora_scale),
        )

    async def mark_training_started(
        self,
        *,
        profile_id: UUID,
        provider_training_id: str,
        brand_style_prompt: str,
        status: BrandLoraStatus = BrandLoraStatus.TRAINING,
        progress: int = 5,
    ) -> BrandLoraView:
        row = await self._session.get(BrandLoraProfile, profile_id, with_for_update=True)
        if row is None:
            raise LookupError("Brand LoRA profile was not found.")
        row.provider_training_id = provider_training_id
        row.brand_style_prompt = brand_style_prompt
        row.status = status.value
        row.training_progress = max(0, min(progress, 99))
        row.error_message = None
        row.updated_at = datetime.now(UTC)
        await self._session.commit()
        loaded = await self.get(profile_id=profile_id, include_references=False)
        if loaded is None:
            raise LookupError("Brand LoRA profile was not found.")
        return loaded

    async def mark_progress(
        self,
        *,
        profile_id: UUID,
        status: BrandLoraStatus,
        progress: int,
        error_message: str | None = None,
    ) -> BrandLoraView:
        row = await self._session.get(BrandLoraProfile, profile_id, with_for_update=True)
        if row is None:
            raise LookupError("Brand LoRA profile was not found.")
        row.status = status.value
        row.training_progress = max(0, min(progress, 100))
        if error_message is not None:
            row.error_message = error_message[:1000]
        row.updated_at = datetime.now(UTC)
        await self._session.commit()
        loaded = await self.get(profile_id=profile_id, include_references=False)
        if loaded is None:
            raise LookupError("Brand LoRA profile was not found.")
        return loaded

    async def mark_ready(
        self,
        *,
        profile_id: UUID,
        brand_style_prompt: str,
        lora_weights_url: str | None,
        provider_version_id: str | None,
        activate: bool = True,
    ) -> BrandLoraView:
        row = await self._session.get(BrandLoraProfile, profile_id, with_for_update=True)
        if row is None:
            raise LookupError("Brand LoRA profile was not found.")
        now = datetime.now(UTC)
        if activate:
            await self._session.execute(
                update(BrandLoraProfile)
                .where(
                    BrandLoraProfile.user_id == row.user_id,
                    BrandLoraProfile.is_active.is_(True),
                    BrandLoraProfile.id != profile_id,
                )
                .values(is_active=False, updated_at=now)
            )
        row.brand_style_prompt = brand_style_prompt
        row.lora_weights_url = lora_weights_url
        row.provider_version_id = provider_version_id
        row.status = BrandLoraStatus.READY.value
        row.training_progress = 100
        row.error_message = None
        row.trained_at = now
        row.is_active = activate
        row.updated_at = now
        await self._session.commit()
        loaded = await self.get(profile_id=profile_id, include_references=False)
        if loaded is None:
            raise LookupError("Brand LoRA profile was not found.")
        return loaded

    async def mark_failed(
        self, *, profile_id: UUID, error_message: str
    ) -> BrandLoraView:
        row = await self._session.get(BrandLoraProfile, profile_id, with_for_update=True)
        if row is None:
            raise LookupError("Brand LoRA profile was not found.")
        row.status = BrandLoraStatus.FAILED.value
        row.training_progress = 100
        row.is_active = False
        row.error_message = error_message[:1000]
        row.updated_at = datetime.now(UTC)
        await self._session.commit()
        loaded = await self.get(profile_id=profile_id, include_references=False)
        if loaded is None:
            raise LookupError("Brand LoRA profile was not found.")
        return loaded

    async def set_active(
        self, *, user_id: UUID, profile_id: UUID, active: bool
    ) -> BrandLoraView:
        row = await self._session.scalar(
            select(BrandLoraProfile)
            .where(
                BrandLoraProfile.id == profile_id,
                BrandLoraProfile.user_id == user_id,
            )
            .with_for_update()
        )
        if row is None:
            raise LookupError("Brand LoRA profile was not found.")
        if row.status != BrandLoraStatus.READY.value:
            raise ValueError("Only ready Brand LoRA profiles can be activated.")
        now = datetime.now(UTC)
        if active:
            await self._session.execute(
                update(BrandLoraProfile)
                .where(
                    BrandLoraProfile.user_id == user_id,
                    BrandLoraProfile.is_active.is_(True),
                    BrandLoraProfile.id != profile_id,
                )
                .values(is_active=False, updated_at=now)
            )
        row.is_active = active
        row.updated_at = now
        await self._session.commit()
        loaded = await self.get_for_user(
            user_id=user_id, profile_id=profile_id, include_references=False
        )
        if loaded is None:
            raise LookupError("Brand LoRA profile was not found.")
        return loaded

    async def archive(self, *, user_id: UUID, profile_id: UUID) -> BrandLoraView:
        row = await self._session.scalar(
            select(BrandLoraProfile)
            .where(
                BrandLoraProfile.id == profile_id,
                BrandLoraProfile.user_id == user_id,
            )
            .with_for_update()
        )
        if row is None:
            raise LookupError("Brand LoRA profile was not found.")
        row.status = BrandLoraStatus.ARCHIVED.value
        row.is_active = False
        row.updated_at = datetime.now(UTC)
        await self._session.commit()
        return _profile_view(row, include_references=False)

    async def list_active_training_ids(self, *, limit: int) -> tuple[UUID, ...]:
        rows = (
            await self._session.scalars(
                select(BrandLoraProfile.id)
                .where(
                    BrandLoraProfile.status.in_(
                        (
                            BrandLoraStatus.QUEUED.value,
                            BrandLoraStatus.TRAINING.value,
                        )
                    )
                )
                .order_by(BrandLoraProfile.updated_at.asc())
                .limit(max(1, min(limit, 200)))
            )
        ).all()
        return tuple(rows)

    async def debit_coins(self, *, user_id: UUID, amount: int) -> int:
        if amount < 0:
            raise BillingValidationError("Debit amount must be non-negative.")
        user = await self._session.get(User, user_id, with_for_update=True)
        if user is None:
            raise LookupError("User was not found.")
        if amount == 0:
            return int(user.ai_coins)
        if user.ai_coins < amount:
            raise BillingValidationError(
                f"Insufficient AI-coin balance for Brand LoRA training "
                f"(need {amount})."
            )
        user.ai_coins -= amount
        await self._session.flush()
        return int(user.ai_coins)

    async def refund_coins(self, *, user_id: UUID, amount: int) -> int:
        if amount <= 0:
            user = await self._session.get(User, user_id)
            return int(user.ai_coins) if user is not None else 0
        user = await self._session.get(User, user_id, with_for_update=True)
        if user is None:
            raise LookupError("User was not found.")
        user.ai_coins = int(user.ai_coins) + amount
        await self._session.commit()
        return int(user.ai_coins)
