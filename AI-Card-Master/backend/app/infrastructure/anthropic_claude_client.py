"""Plan-facing adapter path for Anthropic Opus 4.7 Vision/structured output.

Re-exports the shared infrastructure client used by Claude reasoning/analysis.
"""

from __future__ import annotations

from app.infrastructure.claude.client import Claude47VisionClient

__all__ = ["Claude47VisionClient"]
