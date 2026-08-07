"""Isolated 3D generation module (Adapter Pattern).

Application code depends on ``BaseThreeDEngine`` only. Swap providers via
``THREE_D_PROVIDER`` / ``ThreeDEngineFactory`` without touching use-cases.
"""

from __future__ import annotations

from app.services.three_d.base import BaseThreeDEngine
from app.services.three_d.dto import (
    ThreeDGenerationStage,
    ThreeDTaskLifecycleStatus,
    ThreeDTaskStatusDTO,
)
from app.services.three_d.factory import (
    SUPPORTED_THREE_D_PROVIDERS,
    ThreeDEngineFactory,
    get_three_d_engine,
)
from app.services.three_d.fixtures import MOCK_FIXTURE_BASE, MOCK_RESULT_URLS
from app.services.three_d.mock_adapter import MockThreeDEngineAdapter
from app.services.three_d.storage import (
    ThreeDObjectStorage,
    ThreeDPresignedUrls,
    ThreeDUploadResult,
    get_three_d_object_storage,
)

__all__ = [
    "BaseThreeDEngine",
    "MOCK_FIXTURE_BASE",
    "MOCK_RESULT_URLS",
    "MockThreeDEngineAdapter",
    "SUPPORTED_THREE_D_PROVIDERS",
    "ThreeDEngineFactory",
    "ThreeDGenerationStage",
    "ThreeDObjectStorage",
    "ThreeDPresignedUrls",
    "ThreeDTaskLifecycleStatus",
    "ThreeDTaskStatusDTO",
    "ThreeDUploadResult",
    "get_three_d_engine",
    "get_three_d_object_storage",
]
