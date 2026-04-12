"""Service layer: AI and image processing business logic."""

from app.services.ai_engine import generate_product_image
from app.services.admin_service import (
    AdminErrorLogView,
    AdminNotFoundError,
    AdminService,
    AdminServiceError,
    AdminStatistics,
    AdminUserView,
    AdminValidationError,
)
from app.services.infographic_service import (
    InfographicPackage,
    InfographicService,
    InfographicServiceError,
    InfographicValidationError,
    LLMConfig,
    LLMIntegrationError,
    TextPlacement,
    generate_infographic_package,
)
from app.services.series_generator import (
    SeriesGenerationError,
    SeriesResult,
    SeriesTask,
    build_series_tasks,
    generate_slide_series,
)

__all__ = [
    "generate_product_image",
    "AdminService",
    "AdminServiceError",
    "AdminNotFoundError",
    "AdminValidationError",
    "AdminStatistics",
    "AdminUserView",
    "AdminErrorLogView",
    "LLMConfig",
    "TextPlacement",
    "InfographicPackage",
    "InfographicService",
    "InfographicServiceError",
    "InfographicValidationError",
    "LLMIntegrationError",
    "generate_infographic_package",
    "SeriesTask",
    "SeriesResult",
    "SeriesGenerationError",
    "build_series_tasks",
    "generate_slide_series",
]
