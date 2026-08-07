"""Alembic: query indexes for hot filter columns (user_id/status/created_at/…).

Revision ID: 20260807_0037
Revises: 20260807_0036
Create Date: 2026-08-07 22:40:00
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260807_0037"
down_revision: str | None = "20260807_0036"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# (index_name, table_name, columns)
_INDEXES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("ix_ab_test_experiments_created_at", "ab_test_experiments", ("created_at",)),
    ("ix_ab_test_variants_created_at", "ab_test_variants", ("created_at",)),
    ("ix_ai_strategy_jobs_created_at", "ai_strategy_jobs", ("created_at",)),
    ("ix_oracle_prediction_jobs_created_at", "oracle_prediction_jobs", ("created_at",)),
    ("ix_pain_analysis_jobs_created_at", "pain_analysis_jobs", ("created_at",)),
    ("ix_visual_audit_jobs_created_at", "visual_audit_jobs", ("created_at",)),
    ("ix_competitor_audit_jobs_created_at", "competitor_audit_jobs", ("created_at",)),
    ("ix_brand_dnas_created_at", "brand_dnas", ("created_at",)),
    ("ix_brand_lora_profiles_created_at", "brand_lora_profiles", ("created_at",)),
    ("ix_brand_lora_references_created_at", "brand_lora_references", ("created_at",)),
    ("ix_claude_reasoning_jobs_created_at", "claude_reasoning_jobs", ("created_at",)),
    ("ix_claude_analysis_outbox_created_at", "claude_analysis_outbox", ("created_at",)),
    ("ix_smart_variant_items_created_at", "smart_variant_items", ("created_at",)),
    ("ix_parser_health_created_at", "parser_health", ("created_at",)),
    ("ix_parser_health_status", "parser_health", ("status",)),
    ("ix_sku_items_created_at", "sku_items", ("created_at",)),
    ("ix_stock_snapshots_created_at", "stock_snapshots", ("created_at",)),
    ("ix_bulk_generation_items_created_at", "bulk_generation_items", ("created_at",)),
    ("ix_generation_slides_created_at", "generation_slides", ("created_at",)),
    ("ix_generation_provider_attempts_created_at", "generation_provider_attempts", ("created_at",)),
    ("ix_generation_provider_attempts_status", "generation_provider_attempts", ("status",)),
    ("ix_generation_outbox_created_at", "generation_outbox", ("created_at",)),
    ("ix_eye_of_god_jobs_created_at", "eye_of_god_jobs", ("created_at",)),
    ("ix_audit_logs_created_at", "audit_logs", ("created_at",)),
    ("ix_audit_log_archives_user_id", "audit_log_archives", ("user_id",)),
    ("ix_audit_log_archives_status", "audit_log_archives", ("status",)),
    ("ix_audit_log_archives_created_at", "audit_log_archives", ("created_at",)),
    ("ix_audit_log_archives_event_type", "audit_log_archives", ("event_type",)),
    ("ix_signup_trial_claims_fingerprint_hash", "signup_trial_claims", ("fingerprint_hash",)),
    ("ix_signup_trial_claims_created_at", "signup_trial_claims", ("created_at",)),
)


def upgrade() -> None:
    """Add missing single-column indexes used by hot filters / sorts."""

    for index_name, table_name, columns in _INDEXES:
        cols = ", ".join(columns)
        op.execute(
            f"CREATE INDEX IF NOT EXISTS {index_name} ON {table_name} ({cols})"
        )


def downgrade() -> None:
    """Drop indexes introduced by this revision (safe if already absent)."""

    for index_name, table_name, _columns in reversed(_INDEXES):
        op.execute(f"DROP INDEX IF EXISTS {index_name}")
