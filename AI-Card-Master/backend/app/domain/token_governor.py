"""AI Token & Resource Governor — cost-aware routing policy (plan §69 / Economy 2.0).

Decides whether a workload should:
* hit analytics cache,
* run on a local LLM (Ollama / Llama 3) for routine classification,
* apply Semantic Filtering (Delta) then call Claude,
* or call Claude Haiku / Opus via Smart Reasoning tiers.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.domain.smart_reasoning import ReasoningTaskKind, ReasoningTier, tier_for_task


class StrictDomainModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class ProviderKind(StrEnum):
    """Where the workload should execute."""

    CACHE = "cache"
    LOCAL_OLLAMA = "local_ollama"
    CLAUDE_SIMPLE = "claude_simple"
    CLAUDE_DEEP = "claude_deep"
    REJECT = "reject"


class GovernorAction(StrEnum):
    """High-level decision for callers."""

    USE_CACHE = "use_cache"
    USE_LOCAL = "use_local"
    USE_CLAUDE = "use_claude"
    COMPRESS_THEN_CLAUDE = "compress_then_claude"
    REJECT = "reject"


# Routine text workloads that may run on Ollama when enabled (C6 expanded).
_LOCAL_ELIGIBLE: frozenset[ReasoningTaskKind] = frozenset(
    {
        ReasoningTaskKind.PAIN_ANALYSIS,
        ReasoningTaskKind.ORACLE_ENRICHMENT,
        ReasoningTaskKind.AB_HYPOTHESES,
        ReasoningTaskKind.AI_STRATEGY,
        ReasoningTaskKind.TEXT_CLASSIFICATION,
        ReasoningTaskKind.SEMANTIC_COMPRESSION,
        # JSON-schema text fixes — local pre-filter / Haiku, not Opus.
        ReasoningTaskKind.ZERO_HALLUCINATION,
        ReasoningTaskKind.EXPORT_FAIL_SAFE_FIX,
    }
)

# Vision / deep analysis — never route to local text LLM.
_VISION_LOCKED: frozenset[ReasoningTaskKind] = frozenset(
    {
        ReasoningTaskKind.EYE_OF_GOD,
        ReasoningTaskKind.VISUAL_AUDIT,
        ReasoningTaskKind.COMPETITOR_AUDIT,
        ReasoningTaskKind.CLAUDE_REASONING,
    }
)


class GovernorRequest(StrictDomainModel):
    """Input for a single authorize() decision."""

    task_kind: ReasoningTaskKind
    estimated_input_tokens: int = Field(default=0, ge=0)
    has_vision: bool = False
    cache_hit: bool = False
    semantic_filter_applied: bool = False
    force_provider: ProviderKind | None = None


class GovernorDecision(StrictDomainModel):
    """Routing decision returned by TokenResourceGovernor."""

    action: GovernorAction
    provider: ProviderKind
    apply_semantic_filter: bool = False
    reason: str = Field(min_length=1, max_length=500)
    estimated_input_tokens: int = Field(default=0, ge=0)
    soft_token_limit: int = Field(default=0, ge=0)
    hard_token_limit: int = Field(default=0, ge=0)
    local_eligible: bool = False
    expected_cost_tier: ReasoningTier | None = None

    @field_validator("reason", mode="before")
    @classmethod
    def _strip_reason(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value


class TokenGovernorPolicy(StrictDomainModel):
    """Tunable Economy 2.0 thresholds (from Settings)."""

    enabled: bool = True
    ollama_enabled: bool = False
    soft_input_token_limit: int = Field(default=6_000, ge=100)
    hard_input_token_limit: int = Field(default=24_000, ge=500)
    always_semantic_filter_competitor: bool = True
    prefer_local_for_simple_tier: bool = True

    @model_validator(mode="after")
    def _hard_gte_soft(self) -> TokenGovernorPolicy:
        if self.hard_input_token_limit < self.soft_input_token_limit:
            raise ValueError(
                "hard_input_token_limit must be >= soft_input_token_limit."
            )
        return self


def is_local_eligible(
    kind: ReasoningTaskKind,
    *,
    has_vision: bool = False,
) -> bool:
    """True when the workload may run on Ollama (text-only routine tasks)."""

    if has_vision:
        return False
    if kind in _VISION_LOCKED:
        return False
    return kind in _LOCAL_ELIGIBLE


def provider_for_claude_tier(tier: ReasoningTier) -> ProviderKind:
    if tier is ReasoningTier.DEEP:
        return ProviderKind.CLAUDE_DEEP
    if tier is ReasoningTier.LOCAL:
        return ProviderKind.LOCAL_OLLAMA
    return ProviderKind.CLAUDE_SIMPLE


def decide_governor(
    request: GovernorRequest,
    *,
    policy: TokenGovernorPolicy,
) -> GovernorDecision:
    """Pure policy function — no I/O (plan §69)."""

    soft = policy.soft_input_token_limit
    hard = policy.hard_input_token_limit
    tokens = request.estimated_input_tokens
    tier = tier_for_task(
        request.task_kind,
        has_vision=request.has_vision,
    )
    local_ok = is_local_eligible(
        request.task_kind,
        has_vision=request.has_vision,
    )

    def _base(**overrides: object) -> GovernorDecision:
        payload: dict[str, object] = {
            "estimated_input_tokens": tokens,
            "soft_token_limit": soft,
            "hard_token_limit": hard,
            "local_eligible": local_ok,
            "expected_cost_tier": tier,
            "apply_semantic_filter": False,
        }
        payload.update(overrides)
        return GovernorDecision.model_validate(payload)

    if not policy.enabled:
        return _base(
            action=GovernorAction.USE_CLAUDE,
            provider=provider_for_claude_tier(tier),
            reason="governor_disabled",
        )

    if request.cache_hit:
        return _base(
            action=GovernorAction.USE_CACHE,
            provider=ProviderKind.CACHE,
            reason="analytics_cache_hit",
        )

    if request.force_provider is not None:
        forced = request.force_provider
        if forced is ProviderKind.CACHE:
            action = GovernorAction.USE_CACHE
        elif forced is ProviderKind.LOCAL_OLLAMA:
            action = GovernorAction.USE_LOCAL
        elif forced is ProviderKind.REJECT:
            action = GovernorAction.REJECT
        else:
            action = GovernorAction.USE_CLAUDE
        return _base(
            action=action,
            provider=forced,
            reason=f"force_provider={forced.value}",
        )

    if tokens > hard:
        return _base(
            action=GovernorAction.REJECT,
            provider=ProviderKind.REJECT,
            apply_semantic_filter=True,
            reason=(
                f"estimated_input_tokens={tokens} exceeds hard limit {hard}; "
                "refuse Claude call without compression"
            ),
        )

    needs_compress = False
    if (
        request.task_kind is ReasoningTaskKind.COMPETITOR_AUDIT
        and policy.always_semantic_filter_competitor
        and not request.semantic_filter_applied
    ):
        needs_compress = True
    elif tokens > soft and not request.semantic_filter_applied:
        needs_compress = True

    if needs_compress:
        return _base(
            action=GovernorAction.COMPRESS_THEN_CLAUDE,
            provider=provider_for_claude_tier(tier),
            apply_semantic_filter=True,
            reason=(
                f"semantic_filter_required tokens={tokens} soft_limit={soft} "
                f"task={request.task_kind.value}"
            ),
        )

    if (
        local_ok
        and policy.ollama_enabled
        and policy.prefer_local_for_simple_tier
        and not request.has_vision
    ):
        return _base(
            action=GovernorAction.USE_LOCAL,
            provider=ProviderKind.LOCAL_OLLAMA,
            reason=f"local_llm_for_routine_task={request.task_kind.value}",
        )

    return _base(
        action=GovernorAction.USE_CLAUDE,
        provider=provider_for_claude_tier(tier),
        reason=f"claude_tier={tier.value}",
    )
