"""Unit tests for silent-ban domain helpers and shadow delay."""

from __future__ import annotations

import random

from app.domain.signup_trial import TrialDenialReason
from app.domain.silent_ban import (
    FLAGGED_IP_RATE_LIMIT,
    FLAGGED_IP_RATE_WINDOW_SECONDS,
    SilentFlagReason,
    flag_reason_for,
    pick_shadow_delay_seconds,
    should_silent_flag,
)


def test_should_silent_flag_only_fingerprint_and_subnet() -> None:
    assert should_silent_flag(TrialDenialReason.FINGERPRINT_EXHAUSTED) is True
    assert should_silent_flag(TrialDenialReason.SUBNET_LIMIT) is True
    assert should_silent_flag(TrialDenialReason.PROXY_OR_VPN) is False
    assert should_silent_flag(TrialDenialReason.MISSING_DEVICE_FINGERPRINT) is False
    assert should_silent_flag(TrialDenialReason.STORE_UNAVAILABLE) is False
    assert should_silent_flag(None) is False


def test_flag_reason_mapping() -> None:
    assert (
        flag_reason_for(TrialDenialReason.FINGERPRINT_EXHAUSTED)
        == SilentFlagReason.FINGERPRINT_DUPLICATE.value
    )
    assert (
        flag_reason_for(TrialDenialReason.SUBNET_LIMIT)
        == SilentFlagReason.SUBNET_DUPLICATE.value
    )


def test_flagged_ip_rate_limit_constants() -> None:
    assert FLAGGED_IP_RATE_LIMIT == 1
    assert FLAGGED_IP_RATE_WINDOW_SECONDS == 300


def test_pick_shadow_delay_within_bounds() -> None:
    rng = random.Random(42)
    for _ in range(20):
        delay = pick_shadow_delay_seconds(min_seconds=45, max_seconds=180, rng=rng)
        assert 45 <= delay <= 180
