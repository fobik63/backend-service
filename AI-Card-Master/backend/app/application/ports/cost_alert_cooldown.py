"""Distributed cooldown for cost-budget Telegram alerts (audit R2)."""

from __future__ import annotations

from typing import Protocol


class CostAlertCooldownPort(Protocol):
    """Claim a once-per-window alert slot (Redis SET NX EX preferred)."""

    async def claim(self, *, kind: str, ttl_seconds: float) -> bool:
        """Return True if this process may send the alert for ``kind``."""
