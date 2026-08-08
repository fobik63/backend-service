#!/usr/bin/env python3
"""Seed PostgreSQL with deterministic demo users for frontend / local QA.

Creates 5 accounts with different coin balances and subscription tiers,
then fills each profile with marketplace cards (generation jobs + legacy
generations), A/B experiments, and spending history (payments + charged jobs).

Usage (from ``backend/``)::

    python -m scripts.seed_db
    python -m scripts.seed_db --force   # wipe seed-tagged rows and recreate
    python -m scripts.seed_db --dry-run

Default password for every seed user: ``SeedPass123!``
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import UUID

from sqlalchemy import delete, select

# Allow ``python scripts/seed_db.py`` from backend/ without PYTHONPATH tricks.
_BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from app.core.security import hash_password  # noqa: E402
from app.domain.ab_test import (  # noqa: E402
    AbCreativeStrategy,
    AbExperimentStatus,
    AbVariantStatus,
    CANONICAL_STRATEGIES,
)
from app.domain.generation import (  # noqa: E402
    GenerationEngineMode,
    GenerationJobStatus,
    GenerationPostProcessingMode,
    GenerationProvider,
    SlideStatus,
)
from app.domain.referral import generate_referral_code  # noqa: E402
from app.models.ab_test import AbTestExperiment, AbTestVariant  # noqa: E402
from app.models.database import SessionLocal, engine  # noqa: E402
from app.models.enums import PaymentStatus, SubscriptionStatus, TariffCode  # noqa: E402
from app.models.generation import Generation  # noqa: E402
from app.models.generation_job import GenerationJob, GenerationSlide  # noqa: E402
from app.models.payment import Payment  # noqa: E402
from app.models.user import User  # noqa: E402
from app.services.tariffs import TARIFF_CATALOG  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger("seed_db")

DEFAULT_PASSWORD = "SeedPass123!"
SEED_MARKER = "seed"


@dataclass(frozen=True, slots=True)
class SeedUserSpec:
    email: str
    ai_coins: int
    subscription: SubscriptionStatus
    label: str
    card_count: int
    ab_status: AbExperimentStatus
    payments: tuple[TariffCode, ...]


SEED_USERS: tuple[SeedUserSpec, ...] = (
    SeedUserSpec(
        email="seed.free@ai-card-master.local",
        ai_coins=5,
        subscription=SubscriptionStatus.FREE,
        label="free-trial",
        card_count=1,
        ab_status=AbExperimentStatus.QUEUED,
        payments=(),
    ),
    SeedUserSpec(
        email="seed.start@ai-card-master.local",
        ai_coins=32,
        subscription=SubscriptionStatus.START,
        label="start",
        card_count=2,
        ab_status=AbExperimentStatus.MEASURING,
        payments=(TariffCode.START,),
    ),
    SeedUserSpec(
        email="seed.pro@ai-card-master.local",
        ai_coins=150,
        subscription=SubscriptionStatus.PRO,
        label="pro",
        card_count=3,
        ab_status=AbExperimentStatus.COMPLETED,
        payments=(TariffCode.PRO,),
    ),
    SeedUserSpec(
        email="seed.halfyear@ai-card-master.local",
        ai_coins=900,
        subscription=SubscriptionStatus.HALF_YEAR,
        label="half-year",
        card_count=4,
        ab_status=AbExperimentStatus.COMPLETED,
        payments=(TariffCode.PRO, TariffCode.HALF_YEAR),
    ),
    SeedUserSpec(
        email="seed.year@ai-card-master.local",
        ai_coins=2400,
        subscription=SubscriptionStatus.YEAR,
        label="year",
        card_count=5,
        ab_status=AbExperimentStatus.MEASURING,
        payments=(TariffCode.YEAR,),
    ),
)


def _idem(email: str, kind: str, index: int) -> str:
    return f"{SEED_MARKER}:{email}:{kind}:{index}"


async def _get_user_by_email(session, email: str) -> User | None:
    return await session.scalar(select(User).where(User.email == email))


async def _purge_user_seed_data(session, user_id: UUID) -> None:
    """Remove seed-owned rows so ``--force`` can recreate a clean profile."""

    job_ids = (
        await session.scalars(
            select(GenerationJob.id).where(
                GenerationJob.user_id == user_id,
                GenerationJob.idempotency_key.like(f"{SEED_MARKER}:%"),
            )
        )
    ).all()
    if job_ids:
        await session.execute(
            delete(GenerationSlide).where(GenerationSlide.job_id.in_(job_ids))
        )
        await session.execute(
            delete(GenerationJob).where(GenerationJob.id.in_(job_ids))
        )

    await session.execute(
        delete(Generation).where(
            Generation.user_id == user_id,
            Generation.prompt_used.like(f"[{SEED_MARKER}]%"),
        )
    )

    exp_ids = (
        await session.scalars(
            select(AbTestExperiment.id).where(
                AbTestExperiment.user_id == user_id,
                AbTestExperiment.idempotency_key.like(f"{SEED_MARKER}:%"),
            )
        )
    ).all()
    if exp_ids:
        await session.execute(
            delete(AbTestVariant).where(AbTestVariant.experiment_id.in_(exp_ids))
        )
        await session.execute(
            delete(AbTestExperiment).where(AbTestExperiment.id.in_(exp_ids))
        )

    await session.execute(
        delete(Payment).where(
            Payment.user_id == user_id,
            Payment.yookassa_payment_id.like(f"{SEED_MARKER}-%"),
        )
    )


async def _ensure_user(session, spec: SeedUserSpec, *, force: bool) -> User:
    existing = await _get_user_by_email(session, spec.email)
    if existing is not None:
        if force:
            await _purge_user_seed_data(session, existing.id)
        existing.ai_coins = spec.ai_coins
        existing.subscription_status = spec.subscription
        existing.hashed_password = hash_password(DEFAULT_PASSWORD)
        existing.is_banned = False
        existing.is_flagged = False
        if not existing.referral_code:
            existing.referral_code = generate_referral_code()
        if spec.subscription != SubscriptionStatus.FREE:
            existing.subscription_ends_at = datetime.now(UTC) + timedelta(days=30)
        await session.flush()
        return existing

    user = User(
        email=spec.email,
        hashed_password=hash_password(DEFAULT_PASSWORD),
        subscription_status=spec.subscription,
        ai_coins=spec.ai_coins,
        referral_code=generate_referral_code(),
        subscription_ends_at=(
            datetime.now(UTC) + timedelta(days=30)
            if spec.subscription != SubscriptionStatus.FREE
            else None
        ),
    )
    session.add(user)
    await session.flush()
    return user


async def _seed_cards(session, user: User, spec: SeedUserSpec) -> int:
    """Create completed generation jobs (cards) + legacy Generation rows."""

    created = 0
    now = datetime.now(UTC)
    categories = ("sneakers", "skincare", "kitchen", "gadgets", "home-textile")

    for index in range(1, spec.card_count + 1):
        idem = _idem(spec.email, "card", index)
        exists = await session.scalar(
            select(GenerationJob.id).where(
                GenerationJob.user_id == user.id,
                GenerationJob.idempotency_key == idem,
            )
        )
        if exists is not None:
            continue

        coins_spent = 1 if index % 2 else 3
        completed_at = now - timedelta(hours=index * 6)
        job = GenerationJob(
            user_id=user.id,
            idempotency_key=idem,
            status=GenerationJobStatus.COMPLETED.value,
            progress=100,
            product_category=categories[(index - 1) % len(categories)],
            subscription_status=spec.subscription.value,
            engine_mode=(
                GenerationEngineMode.PREMIUM.value
                if spec.subscription.is_paid()
                else GenerationEngineMode.STANDARD.value
            ),
            post_processing_mode=(
                GenerationPostProcessingMode.HD_FACE_FIX.value
                if coins_spent == 3
                else GenerationPostProcessingMode.FAST.value
            ),
            input_object_key=f"seed/{spec.label}/input-{index}.jpg",
            thumbnail_object_key=f"seed/{spec.label}/thumb-{index}.jpg",
            marketplace_text={
                "title": f"Seed card {index} · {spec.label}",
                "bullets": [
                    "Демо-карточка для фронтенда",
                    f"Tier: {spec.subscription.value}",
                ],
            },
            provider_used=GenerationProvider.MIDJOURNEY.value,
            coin_charged=True,
            coins_charged=coins_spent,
            created_at=completed_at - timedelta(minutes=5),
            updated_at=completed_at,
            completed_at=completed_at,
        )
        session.add(job)
        await session.flush()

        for position, slide_key in enumerate(
            ("cover", "benefit", "social", "offer", "details"), start=1
        ):
            session.add(
                GenerationSlide(
                    job_id=job.id,
                    slide_key=slide_key,
                    position=position,
                    status=SlideStatus.COMPLETED.value,
                    progress=100,
                    selected_style=f"seed-{slide_key}",
                    prompt_used=f"[{SEED_MARKER}] {spec.label} slide {slide_key}",
                    provider_used=GenerationProvider.MIDJOURNEY.value,
                    result_object_key=(
                        f"seed/{spec.label}/job-{index}/{slide_key}.jpg"
                    ),
                    result_mime_type="image/jpeg",
                    completed_at=completed_at,
                )
            )

        session.add(
            Generation(
                user_id=user.id,
                input_image_url=f"https://cdn.example.local/seed/{spec.label}/in-{index}.jpg",
                result_image_url=(
                    f"https://cdn.example.local/seed/{spec.label}/out-{index}.jpg"
                ),
                prompt_used=f"[{SEED_MARKER}] marketplace card {index} for {spec.label}",
                created_at=completed_at,
            )
        )
        created += 1

    return created


async def _seed_ab_test(session, user: User, spec: SeedUserSpec) -> bool:
    idem = _idem(spec.email, "ab", 1)
    existing = await session.scalar(
        select(AbTestExperiment.id).where(
            AbTestExperiment.user_id == user.id,
            AbTestExperiment.idempotency_key == idem,
        )
    )
    if existing is not None:
        return False

    now = datetime.now(UTC)
    is_completed = spec.ab_status == AbExperimentStatus.COMPLETED
    is_measuring = spec.ab_status == AbExperimentStatus.MEASURING

    experiment = AbTestExperiment(
        user_id=user.id,
        idempotency_key=idem,
        status=spec.ab_status.value,
        model_name="claude-seed",
        marketplace="wildberries",
        niche_key=f"seed-{spec.label}",
        sku=f"SEED-{spec.label.upper()}-001",
        nm_id=f"9{abs(hash(spec.email)) % 10_000_000:07d}",
        campaign_id=f"seed-campaign-{spec.label}",
        product_payload={
            "title": f"Seed product ({spec.label})",
            "brand": "AI Card Master Seed",
        },
        config={"duration_days": 7, "source": SEED_MARKER},
        hypotheses_payload=[
            {"strategy": s.value, "title": f"Hypothesis {s.value}"}
            for s in CANONICAL_STRATEGIES
        ],
        measurement_started_at=now - timedelta(days=3) if is_measuring or is_completed else None,
        measurement_ends_at=now + timedelta(days=4) if is_measuring else (
            now - timedelta(hours=1) if is_completed else None
        ),
        completed_at=now - timedelta(hours=1) if is_completed else None,
        input_tokens=1200,
        output_tokens=800,
    )
    session.add(experiment)
    await session.flush()

    metrics = (
        (12_400, 620, 5.0, 890.0),
        (11_800, 472, 4.0, 760.0),
        (13_100, 786, 6.0, 940.0),
    )
    winner_index = 2
    winner_id: UUID | None = None

    for position, strategy in enumerate(CANONICAL_STRATEGIES, start=1):
        impressions, clicks, ctr, spend = metrics[position - 1]
        if is_completed:
            status = (
                AbVariantStatus.WINNER
                if position - 1 == winner_index
                else AbVariantStatus.LOSER
            )
        elif is_measuring:
            status = AbVariantStatus.MEASURING
        else:
            status = AbVariantStatus.PENDING
            impressions = clicks = 0
            ctr = 0.0
            spend = None

        variant = AbTestVariant(
            experiment_id=experiment.id,
            position=position,
            strategy=strategy.value,
            status=status.value,
            title=f"{strategy.value.replace('_', ' ').title()} · {spec.label}",
            main_image_brief=f"Seed brief for {strategy.value}",
            offer_hook="−20% только сегодня" if strategy is AbCreativeStrategy.OFFER_URGENCY else None,
            headline=f"Seed headline ({strategy.value})",
            rationale="Deterministic seed creative for local UI.",
            prompt_for_generator=f"[{SEED_MARKER}] generate {strategy.value}",
            confidence=0.72 + position * 0.05,
            impressions=impressions,
            clicks=clicks,
            ctr_pct=ctr,
            spend=spend,
            metrics_sampled_at=now if status != AbVariantStatus.PENDING else None,
        )
        session.add(variant)
        await session.flush()
        if is_completed and position - 1 == winner_index:
            winner_id = variant.id

    if winner_id is not None:
        experiment.winner_variant_id = winner_id
        experiment.resolution_result = {
            "winner_strategy": CANONICAL_STRATEGIES[winner_index].value,
            "reason": "Highest CTR in seed dataset",
        }

    return True


async def _seed_payments(session, user: User, spec: SeedUserSpec) -> int:
    created = 0
    now = datetime.now(UTC)
    for index, tariff_code in enumerate(spec.payments, start=1):
        payment_id = f"{SEED_MARKER}-{spec.label}-{tariff_code.value}-{index}"
        exists = await session.scalar(
            select(Payment.id).where(Payment.yookassa_payment_id == payment_id)
        )
        if exists is not None:
            continue
        plan = TARIFF_CATALOG[tariff_code]
        session.add(
            Payment(
                user_id=user.id,
                tariff_code=tariff_code,
                yookassa_payment_id=payment_id,
                amount_rub=plan.price_rub,
                currency="RUB",
                status=PaymentStatus.SUCCEEDED,
                confirmation_url=None,
                description=f"[{SEED_MARKER}] {plan.title} for {spec.email}",
                created_at=now - timedelta(days=14 * index),
                processed_at=now - timedelta(days=14 * index) + timedelta(minutes=2),
            )
        )
        created += 1

    # Optional pending payment for richer spending UI on paid tiers.
    if spec.payments:
        pending_id = f"{SEED_MARKER}-{spec.label}-pending-1"
        exists = await session.scalar(
            select(Payment.id).where(Payment.yookassa_payment_id == pending_id)
        )
        if exists is None:
            session.add(
                Payment(
                    user_id=user.id,
                    tariff_code=spec.payments[-1],
                    yookassa_payment_id=pending_id,
                    amount_rub=Decimal("990.00"),
                    currency="RUB",
                    status=PaymentStatus.PENDING,
                    confirmation_url="https://yookassa.example.local/seed-checkout",
                    description=f"[{SEED_MARKER}] pending top-up for {spec.email}",
                )
            )
            created += 1
    return created


async def seed(*, force: bool, dry_run: bool) -> None:
    async with SessionLocal() as session:
        summary: list[str] = []
        for spec in SEED_USERS:
            user = await _ensure_user(session, spec, force=force)
            cards = await _seed_cards(session, user, spec)
            ab_created = await _seed_ab_test(session, user, spec)
            payments = await _seed_payments(session, user, spec)
            summary.append(
                f"{spec.email}: id={user.id} coins={user.ai_coins} "
                f"tier={user.subscription_status.value} "
                f"cards+={cards} ab={'yes' if ab_created else 'skip'} "
                f"payments+={payments}"
            )

        if dry_run:
            await session.rollback()
            logger.info("Dry-run complete (rolled back). Planned:")
        else:
            await session.commit()
            logger.info("Seed committed.")

        for line in summary:
            logger.info("  %s", line)
        logger.info("Password for all seed users: %s", DEFAULT_PASSWORD)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Seed AI-Card-Master DB with demo users for frontend work.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Delete existing seed-tagged rows for seed emails and recreate them.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Compute inserts but roll back the transaction.",
    )
    return parser


async def _async_main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        await seed(force=args.force, dry_run=args.dry_run)
    except Exception:
        logger.exception("Seed failed")
        return 1
    finally:
        await engine.dispose()
    return 0


def main(argv: list[str] | None = None) -> None:
    raise SystemExit(asyncio.run(_async_main(argv)))


if __name__ == "__main__":
    main()
