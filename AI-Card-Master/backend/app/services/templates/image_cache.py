"""In-memory LRU cache for remote / local canvas image assets."""

from __future__ import annotations

import asyncio
import logging
import threading
from collections import OrderedDict
from pathlib import Path
from typing import Final
from urllib.parse import unquote, urlparse

import httpx

logger = logging.getLogger(__name__)

DEFAULT_MAX_ENTRIES: Final[int] = 128
DEFAULT_MAX_BYTES: Final[int] = 128 * 1024 * 1024  # 128 MiB
DEFAULT_TIMEOUT_SECONDS: Final[float] = 20.0
MAX_DOWNLOAD_BYTES: Final[int] = 40 * 1024 * 1024  # 40 MiB per asset


class ImageAssetCacheError(RuntimeError):
    """Raised when an image asset cannot be loaded."""


class ImageAssetCache:
    """Thread-safe LRU cache of image bytes keyed by URL / path."""

    def __init__(
        self,
        *,
        max_entries: int = DEFAULT_MAX_ENTRIES,
        max_bytes: int = DEFAULT_MAX_BYTES,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        if max_entries < 1:
            raise ValueError("max_entries must be >= 1")
        if max_bytes < 1024:
            raise ValueError("max_bytes must be >= 1024")
        self._max_entries = max_entries
        self._max_bytes = max_bytes
        self._timeout = httpx.Timeout(timeout_seconds)
        self._http_client = http_client
        self._owned_client = False
        self._lock = threading.RLock()
        self._async_locks: dict[str, asyncio.Lock] = {}
        self._async_locks_guard = asyncio.Lock()
        self._store: OrderedDict[str, bytes] = OrderedDict()
        self._total_bytes = 0

    async def get(self, url: str) -> bytes:
        """Return image bytes for ``url``, downloading or reading as needed."""

        key = url.strip()
        if not key:
            raise ImageAssetCacheError("Image URL cannot be empty.")

        cached = self._get_cached(key)
        if cached is not None:
            return cached

        lock = await self._lock_for(key)
        async with lock:
            cached = self._get_cached(key)
            if cached is not None:
                return cached
            payload = await self._load(key)
            self._put(key, payload)
            return payload

    def put(self, url: str, payload: bytes) -> None:
        """Manually seed the cache (useful for unit tests)."""

        if not payload:
            raise ImageAssetCacheError("Cannot cache empty image payload.")
        self._put(url.strip(), bytes(payload))

    def clear(self) -> None:
        with self._lock:
            self._store.clear()
            self._total_bytes = 0

    @property
    def entry_count(self) -> int:
        with self._lock:
            return len(self._store)

    @property
    def total_bytes(self) -> int:
        with self._lock:
            return self._total_bytes

    async def aclose(self) -> None:
        if self._owned_client and self._http_client is not None:
            await self._http_client.aclose()
            self._http_client = None
            self._owned_client = False

    def _get_cached(self, key: str) -> bytes | None:
        with self._lock:
            payload = self._store.get(key)
            if payload is None:
                return None
            self._store.move_to_end(key)
            return payload

    def _put(self, key: str, payload: bytes) -> None:
        size = len(payload)
        if size > self._max_bytes:
            # Too large to cache; skip silently after load.
            logger.debug("Skipping cache for oversized asset %s (%s bytes)", key, size)
            return
        with self._lock:
            existing = self._store.pop(key, None)
            if existing is not None:
                self._total_bytes -= len(existing)
            while (
                self._store
                and (
                    len(self._store) >= self._max_entries
                    or self._total_bytes + size > self._max_bytes
                )
            ):
                _, evicted = self._store.popitem(last=False)
                self._total_bytes -= len(evicted)
            self._store[key] = payload
            self._total_bytes += size

    async def _lock_for(self, key: str) -> asyncio.Lock:
        async with self._async_locks_guard:
            lock = self._async_locks.get(key)
            if lock is None:
                lock = asyncio.Lock()
                self._async_locks[key] = lock
            return lock

    async def _load(self, key: str) -> bytes:
        parsed = urlparse(key)
        scheme = (parsed.scheme or "").lower()

        if scheme in {"http", "https"}:
            return await self._download_http(key)

        if scheme == "file":
            path = Path(unquote(parsed.path))
            # Windows file:///C:/... → path may start with /C:/
            if path.as_posix().startswith("/") and len(path.parts) > 1 and path.parts[0] == "/":
                # Keep Path as-is; pathlib handles /C:/foo on Windows in most cases.
                pass
            if len(parsed.netloc) == 1 and parsed.netloc.isalpha():
                # file://C:/Windows/... rare form
                path = Path(f"{parsed.netloc}:{unquote(parsed.path)}")
            return await asyncio.to_thread(self._read_local, path)

        if scheme == "data":
            return _decode_data_url(key)

        # Bare filesystem path (absolute or relative).
        if scheme == "" or len(scheme) == 1:
            return await asyncio.to_thread(self._read_local, Path(key))

        raise ImageAssetCacheError(f"Unsupported image URL scheme: {scheme!r}")

    async def _download_http(self, url: str) -> bytes:
        client = await self._client()
        try:
            response = await client.get(url)
            response.raise_for_status()
        except httpx.TimeoutException as exc:
            raise ImageAssetCacheError(f"Timed out downloading image: {url}") from exc
        except httpx.HTTPStatusError as exc:
            raise ImageAssetCacheError(
                f"HTTP {exc.response.status_code} downloading image: {url}"
            ) from exc
        except httpx.HTTPError as exc:
            raise ImageAssetCacheError(f"Failed to download image: {url}") from exc

        payload = response.content
        if not payload:
            raise ImageAssetCacheError(f"Empty image response: {url}")
        if len(payload) > MAX_DOWNLOAD_BYTES:
            raise ImageAssetCacheError(
                f"Image exceeds {MAX_DOWNLOAD_BYTES} byte limit: {url}"
            )
        return payload

    async def _client(self) -> httpx.AsyncClient:
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(
                timeout=self._timeout,
                follow_redirects=True,
                headers={"User-Agent": "AI-Card-Master-CanvasRenderer/1.0"},
            )
            self._owned_client = True
        return self._http_client

    @staticmethod
    def _read_local(path: Path) -> bytes:
        resolved = path.expanduser()
        if not resolved.is_file():
            raise ImageAssetCacheError(f"Local image not found: {resolved}")
        payload = resolved.read_bytes()
        if not payload:
            raise ImageAssetCacheError(f"Local image is empty: {resolved}")
        if len(payload) > MAX_DOWNLOAD_BYTES:
            raise ImageAssetCacheError(
                f"Local image exceeds {MAX_DOWNLOAD_BYTES} byte limit: {resolved}"
            )
        return payload


def _decode_data_url(data_url: str) -> bytes:
    import base64
    import binascii

    if "," not in data_url:
        raise ImageAssetCacheError("Malformed data URL.")
    header, payload = data_url.split(",", 1)
    try:
        if ";base64" in header.lower():
            return base64.b64decode(payload, validate=False)
        from urllib.parse import unquote_to_bytes

        return unquote_to_bytes(payload)
    except (binascii.Error, ValueError) as exc:
        raise ImageAssetCacheError("Failed to decode data URL image.") from exc


_GLOBAL_IMAGE_CACHE: ImageAssetCache | None = None
_GLOBAL_IMAGE_LOCK = threading.Lock()


def get_image_asset_cache() -> ImageAssetCache:
    """Process-singleton image asset cache."""

    global _GLOBAL_IMAGE_CACHE
    if _GLOBAL_IMAGE_CACHE is not None:
        return _GLOBAL_IMAGE_CACHE
    with _GLOBAL_IMAGE_LOCK:
        if _GLOBAL_IMAGE_CACHE is None:
            _GLOBAL_IMAGE_CACHE = ImageAssetCache()
        return _GLOBAL_IMAGE_CACHE
