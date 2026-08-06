"""Referral domain primitives independent from persistence and HTTP."""

from __future__ import annotations

import secrets
from dataclasses import dataclass

REFERRAL_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
REFERRAL_CODE_LENGTH = 8


@dataclass(frozen=True, slots=True)
class ReferralStats:
    """Referral counters returned to the current user."""

    referral_code: str
    invited_count: int
    paid_invited_count: int
    earned_free_credits: int
    bonus_credits_per_friend: int


def generate_referral_code() -> str:
    """Generate a human-readable referral code without ambiguous characters."""

    return "".join(
        secrets.choice(REFERRAL_CODE_ALPHABET) for _ in range(REFERRAL_CODE_LENGTH)
    )


def normalize_referral_code(value: str) -> str:
    """Normalize user-entered referral codes before lookup."""

    return value.strip().upper().replace("-", "").replace(" ", "")
