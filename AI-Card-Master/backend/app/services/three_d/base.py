"""Abstract 3D generation engine (Adapter Pattern target interface)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from app.services.three_d.dto import ThreeDTaskStatusDTO


class BaseThreeDEngine(ABC):
    """Provider-neutral contract for asynchronous 3D asset generation.

    Concrete adapters (Meshy, Tripo3D, RunPod GPU, mock) implement this
    interface so application/use-case code never depends on a vendor SDK.
    """

    async def ensure_available(self) -> None:
        """Fail fast when the provider circuit is OPEN (override in adapters).

        Default is a no-op so mock / local engines stay available.
        """

        return None

    async def aclose(self) -> None:
        """Release owned HTTP clients / background tasks (default: no-op)."""

        return None

    @abstractmethod
    async def create_generation_task(
        self,
        prompt: str,
        image_url: str | None,
        params: dict[str, Any],
    ) -> str:
        """Enqueue a 3D generation job.

        Returns:
            Opaque ``provider_task_id`` for subsequent status / cancel calls.
        """

    @abstractmethod
    async def get_task_status(self, provider_task_id: str) -> ThreeDTaskStatusDTO:
        """Poll normalized lifecycle status for ``provider_task_id``."""

    @abstractmethod
    async def cancel_task(self, provider_task_id: str) -> bool:
        """Request cancellation.

        Returns:
            ``True`` if the task was cancelled (or already cancellable and
            marked cancelled); ``False`` if unknown or already terminal.
        """
