"""SQLAlchemy adapter for signup trial fingerprint claims."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.signup_trial import TrialDenialReason
from app.models.signup_trial import SignupTrialClaim


class SignupTrialClaimRepository:
    """Persist and look up durable signup trial fingerprint claims."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def has_granted_trial(self, *, fingerprint_hash: str) -> bool:
        result = await self._session.scalar(
            select(SignupTrialClaim.id)
            .where(
                SignupTrialClaim.fingerprint_hash == fingerprint_hash,
                SignupTrialClaim.trial_granted.is_(True),
            )
            .limit(1)
        )
        return result is not None

    async def has_fingerprint(self, *, fingerprint_hash: str) -> bool:
        normalized = (fingerprint_hash or "").strip()
        if not normalized:
            return False
        result = await self._session.scalar(
            select(SignupTrialClaim.id)
            .where(SignupTrialClaim.fingerprint_hash == normalized[:64])
            .limit(1)
        )
        return result is not None

    async def count_accounts_for_subnet(self, *, subnet: str) -> int:
        normalized = (subnet or "").strip()
        if not normalized:
            return 0
        result = await self._session.scalar(
            select(func.count(func.distinct(SignupTrialClaim.user_id))).where(
                SignupTrialClaim.ip_subnet == normalized
            )
        )
        return int(result or 0)

    async def record_claim(
        self,
        *,
        user_id: UUID,
        fingerprint_hash: str | None,
        client_ip: str | None,
        ip_subnet: str | None,
        trial_granted: bool,
        denial_reason: TrialDenialReason | None,
        user_agent: str | None,
        accept_language: str | None,
    ) -> None:
        claim = SignupTrialClaim(
            user_id=user_id,
            fingerprint_hash=fingerprint_hash,
            client_ip=(client_ip or None),
            ip_subnet=ip_subnet,
            trial_granted=trial_granted,
            denial_reason=denial_reason.value if denial_reason else None,
            user_agent=(user_agent or None)[:512] if user_agent else None,
            accept_language=(accept_language or None)[:128] if accept_language else None,
        )
        self._session.add(claim)
        await self._session.commit()
