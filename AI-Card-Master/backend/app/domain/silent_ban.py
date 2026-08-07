"""Silent ban (shadow restriction) rules for signup abusers.

Flagged users must never see an explicit block (no 403 on register).
They receive a successful account with zero trial coins; further abuse
signals route generation to a low-priority shadow queue and tighten IP
rate limits so the experience looks like ordinary load / rate pressure.
"""

from __future__ import annotations

import random
from enum import StrEnum

from app.domain.signup_trial import TrialDenialReason


class SilentFlagReason(StrEnum):
    """Persisted ``User.flag_reason`` values for silent bans."""

    FINGERPRINT_DUPLICATE = "fingerprint_duplicate"
    SUBNET_DUPLICATE = "subnet_duplicate"


# Only fingerprint / subnet duplicates trigger silent flagging.
# Proxy / missing-FP / store outages still deny trial coins without flagging.
_SILENT_FLAG_DENIALS: frozenset[TrialDenialReason] = frozenset(
    {
        TrialDenialReason.FINGERPRINT_EXHAUSTED,
        TrialDenialReason.SUBNET_LIMIT,
    }
)

_DENIAL_TO_FLAG_REASON: dict[TrialDenialReason, SilentFlagReason] = {
    TrialDenialReason.FINGERPRINT_EXHAUSTED: SilentFlagReason.FINGERPRINT_DUPLICATE,
    TrialDenialReason.SUBNET_LIMIT: SilentFlagReason.SUBNET_DUPLICATE,
}

# Hard rate limit for flagged IPs: 1 request / 5 minutes.
FLAGGED_IP_RATE_LIMIT = 1
FLAGGED_IP_RATE_WINDOW_SECONDS = 300

DEFAULT_SHADOW_DELAY_MIN_SECONDS = 45
DEFAULT_SHADOW_DELAY_MAX_SECONDS = 180

SHADOW_LOAD_ERROR_MESSAGE = (
    "Generation timed out while loading provider response. Please try again."
)


def should_silent_flag(denial_reason: TrialDenialReason | None) -> bool:
    """True when anti-abuse denial must mark the user as silently flagged."""

    return denial_reason in _SILENT_FLAG_DENIALS


def flag_reason_for(denial_reason: TrialDenialReason) -> str:
    """Map a trial denial to a stable ``User.flag_reason`` string."""

    mapped = _DENIAL_TO_FLAG_REASON.get(denial_reason)
    if mapped is not None:
        return mapped.value
    return denial_reason.value


def pick_shadow_delay_seconds(
    *,
    min_seconds: int = DEFAULT_SHADOW_DELAY_MIN_SECONDS,
    max_seconds: int = DEFAULT_SHADOW_DELAY_MAX_SECONDS,
    rng: random.Random | None = None,
) -> int:
    """Random inflated delay before the shadow worker emits a fake load error."""

    low = max(1, int(min_seconds))
    high = max(low, int(max_seconds))
    picker = rng if rng is not None else random.SystemRandom()
    return int(picker.randint(low, high))
