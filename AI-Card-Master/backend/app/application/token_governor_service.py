"""Token & Resource Governor application service (plan §69)."""

from __future__ import annotations

from app.domain.token_governor import (
    GovernorDecision,
    GovernorRequest,
    TokenGovernorPolicy,
    decide_governor,
)


class TokenResourceGovernor:
    """Application façade over pure ``decide_governor`` policy."""

    def __init__(self, *, policy: TokenGovernorPolicy) -> None:
        self._policy = policy

    @property
    def policy(self) -> TokenGovernorPolicy:
        return self._policy

    def authorize(self, request: GovernorRequest) -> GovernorDecision:
        return decide_governor(request, policy=self._policy)
