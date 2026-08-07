"""Plan-facing adapter path for Anthropic Opus 4.7 Vision/structured output.

Re-exports the shared infrastructure client used by Claude reasoning/analysis.
Import is lazy so optional ``anthropic`` is not required at package load time.
"""

from __future__ import annotations

from typing import Any

__all__ = ["Claude47VisionClient"]


def __getattr__(name: str) -> Any:
    if name == "Claude47VisionClient":
        from app.infrastructure.claude.client import Claude47VisionClient

        return Claude47VisionClient
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
