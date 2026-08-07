"""Isolated 3D generation module (Adapter Pattern).

Application code depends on ``BaseThreeDEngine`` only. Swap providers via
``THREE_D_PROVIDER`` / ``ThreeDEngineFactory`` without touching use-cases.
"""

from __future__ import annotations

from app.services.three_d.adapters import MeshyEngineAdapter, Tripo3DEngineAdapter
from app.services.three_d.base import BaseThreeDEngine
from app.services.three_d.dto import (
    ThreeDGenerationStage,
    ThreeDTaskLifecycleStatus,
    ThreeDTaskStatusDTO,
)
from app.services.three_d.errors import ThreeDServiceUnavailableError
from app.services.three_d.factory import (
    SUPPORTED_THREE_D_PROVIDERS,
    ThreeDEngineFactory,
    close_three_d_engine,
    get_three_d_engine,
)
from app.services.three_d.failover import FailoverThreeDEngine
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
    "FailoverThreeDEngine",
    "MOCK_FIXTURE_BASE",
    "MOCK_RESULT_URLS",
    "MeshyEngineAdapter",
    "MockThreeDEngineAdapter",
    "SUPPORTED_THREE_D_PROVIDERS",
    "ThreeDEngineFactory",
    "ThreeDGenerationStage",
    "ThreeDObjectStorage",
    "ThreeDPresignedUrls",
    "ThreeDServiceUnavailableError",
    "ThreeDTaskLifecycleStatus",
    "ThreeDTaskStatusDTO",
    "ThreeDUploadResult",
    "Tripo3DEngineAdapter",
    "close_three_d_engine",
    "get_three_d_engine",
    "get_three_d_object_storage",
]
