"""Model layer: Pydantic schemas and SQLAlchemy entities."""

from app.models.ab_test import AbTestExperiment, AbTestVariant
from app.models.ai_strategy import AiStrategyJob
from app.models.api_usage_cost import ApiUsageCost
from app.models.audit_log import AuditLog, AuditLogArchive
from app.models.base import Base
from app.models.brand_dna import BrandDNA
from app.models.brand_lora import BrandLoraProfile, BrandLoraReference
from app.models.bulk_generation import (
    BulkGenerationBatch,
    BulkGenerationItem,
    UserPushNotification,
)
from app.models.claude_reasoning import ClaudeReasoningJob, ClaudeReasoningOutbox
from app.models.coin_hold import CoinHold
from app.models.coin_purchase import CoinPurchase
from app.models.competitor_audit import CompetitorAuditJob
from app.models.eye_of_god import EyeOfGodJob
from app.models.generation import Generation
from app.models.generation_error_log import GenerationErrorLog
from app.models.generation_job import (
    GenerationJob,
    GenerationOutbox,
    GenerationProviderAttempt,
    GenerationSlide,
    GenerationWebhookEvent,
)
from app.models.idempotency_record import IdempotencyRecord
from app.models.marketplace_export import (
    MarketplaceCredential,
    MarketplaceExport,
    MarketplacePublication,
)
from app.models.oracle import OraclePredictionJob
from app.models.pain_analysis import PainAnalysisJob
from app.models.payment import Payment
from app.models.signup_trial import SignupTrialClaim
from app.models.smart_variant import SmartVariantItem, SmartVariantSync
from app.models.stock_parser import ParserHealth, SkuItem, StockSnapshot
from app.models.style_preset_selection import StylePresetSelection
from app.models.template import CustomFont, Template, UserSavedDesign
from app.models.three_d import (
    GpuRentalSession,
    ThreeDAsset,
    ThreeDTask,
    ThreeDVideoTask,
    VideoAsset,
)
from app.models.user import User
from app.models.visual_audit import VisualAuditJob
from app.models.winback import WinbackOffer, WinbackStyleNotification
from app.models.workspace import Workspace, WorkspaceMember, WorkspaceSharedGeneration

__all__ = [
    "Base",
    "ApiUsageCost",
    "AuditLog",
    "AuditLogArchive",
    "AbTestExperiment",
    "AbTestVariant",
    "BulkGenerationBatch",
    "BulkGenerationItem",
    "BrandLoraProfile",
    "BrandLoraReference",
    "BrandDNA",
    "AiStrategyJob",
    "ClaudeReasoningJob",
    "ClaudeReasoningOutbox",
    "PainAnalysisJob",
    "ParserHealth",
    "SkuItem",
    "StockSnapshot",
    "EyeOfGodJob",
    "CompetitorAuditJob",
    "VisualAuditJob",
    "OraclePredictionJob",
    "Generation",
    "GenerationErrorLog",
    "GenerationJob",
    "GenerationOutbox",
    "GenerationProviderAttempt",
    "GenerationSlide",
    "GenerationWebhookEvent",
    "MarketplaceCredential",
    "MarketplaceExport",
    "MarketplacePublication",
    "Payment",
    "CoinPurchase",
    "CoinHold",
    "IdempotencyRecord",
    "SmartVariantItem",
    "SmartVariantSync",
    "StylePresetSelection",
    "CustomFont",
    "Template",
    "UserSavedDesign",
    "User",
    "UserPushNotification",
    "SignupTrialClaim",
    "WinbackOffer",
    "WinbackStyleNotification",
    "ThreeDTask",
    "ThreeDAsset",
    "ThreeDVideoTask",
    "VideoAsset",
    "GpuRentalSession",
    "Workspace",
    "WorkspaceMember",
    "WorkspaceSharedGeneration",
]
