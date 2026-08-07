"""Ensure backend root is on sys.path for pytest imports."""

from __future__ import annotations

import sys
from pathlib import Path

_BACKEND_ROOT = Path(__file__).resolve().parent
_root_str = str(_BACKEND_ROOT)
if _root_str not in sys.path:
    sys.path.insert(0, _root_str)
