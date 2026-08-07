"""External 3D provider adapters (Meshy, Tripo3D, …)."""

from __future__ import annotations

from app.services.three_d.adapters.meshy import MeshyEngineAdapter
from app.services.three_d.adapters.tripo3d import Tripo3DEngineAdapter

__all__ = [
    "MeshyEngineAdapter",
    "Tripo3DEngineAdapter",
]
