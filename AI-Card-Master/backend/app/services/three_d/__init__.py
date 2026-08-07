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
from app.services.three_d.errors import (
    FFmpegEncodeError,
    HeadlessGLError,
    MeshLoadError,
    RenderEngineError,
    ThreeDServiceUnavailableError,
)
from app.services.three_d.factory import (
    SUPPORTED_THREE_D_PROVIDERS,
    ThreeDEngineFactory,
    close_three_d_engine,
    get_three_d_engine,
)
from app.services.three_d.failover import FailoverThreeDEngine
from app.services.three_d.fixtures import MOCK_FIXTURE_BASE, MOCK_RESULT_URLS
from app.services.three_d.mock_adapter import MockThreeDEngineAdapter
from app.services.three_d.render_engine import (
    Offscreen3DRenderer,
    OrbitVideoResult,
    RenderEngineConfig,
)
from app.services.three_d.storage import (
    ThreeDObjectStorage,
    ThreeDPresignedUrls,
    ThreeDUploadResult,
    get_three_d_object_storage,
)
from app.services.three_d.styles import (
    ALLOWED_FRAME_ASPECTS,
    LIGHTING_PRESETS,
    LightRole,
    LightSourceDTO,
    LightingPresetDTO,
    LightingPresetName,
    RenderSettingsDTO,
    ShadowCatcherFloorMesh,
    ShadowCatcherFloorSettings,
    StudioBackgroundMode,
    build_shadow_catcher_floor,
    get_lighting_preset,
)
from app.services.three_d.video_storage import (
    VideoAssetUploader,
    VideoPresignedUrls,
    VideoUploadResult,
    get_video_asset_uploader,
)

__all__ = [
    "ALLOWED_FRAME_ASPECTS",
    "BaseThreeDEngine",
    "FFmpegEncodeError",
    "FailoverThreeDEngine",
    "HeadlessGLError",
    "LIGHTING_PRESETS",
    "LightRole",
    "LightSourceDTO",
    "LightingPresetDTO",
    "LightingPresetName",
    "MOCK_FIXTURE_BASE",
    "MOCK_RESULT_URLS",
    "MeshLoadError",
    "MeshyEngineAdapter",
    "MockThreeDEngineAdapter",
    "Offscreen3DRenderer",
    "OrbitVideoResult",
    "RenderEngineConfig",
    "RenderEngineError",
    "RenderSettingsDTO",
    "SUPPORTED_THREE_D_PROVIDERS",
    "ShadowCatcherFloorMesh",
    "ShadowCatcherFloorSettings",
    "StudioBackgroundMode",
    "ThreeDEngineFactory",
    "ThreeDGenerationStage",
    "ThreeDObjectStorage",
    "ThreeDPresignedUrls",
    "ThreeDServiceUnavailableError",
    "ThreeDTaskLifecycleStatus",
    "ThreeDTaskStatusDTO",
    "ThreeDUploadResult",
    "Tripo3DEngineAdapter",
    "VideoAssetUploader",
    "VideoPresignedUrls",
    "VideoUploadResult",
    "build_shadow_catcher_floor",
    "close_three_d_engine",
    "get_lighting_preset",
    "get_three_d_engine",
    "get_three_d_object_storage",
    "get_video_asset_uploader",
]
