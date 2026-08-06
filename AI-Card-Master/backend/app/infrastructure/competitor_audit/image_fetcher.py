"""Download competitor gallery photos for Claude Vision (plan §78)."""

from __future__ import annotations

import logging

import httpx

from app.domain.bulk_generation import detect_image_mime

logger = logging.getLogger(__name__)


class CompetitorCardImageFetcher:
    """httpx gallery fetcher for competitor-audit Vision stage."""

    def __init__(
        self,
        *,
        timeout_seconds: float = 20.0,
        max_bytes: int = 8_000_000,
        user_agent: str = (
            "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
            "AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148"
        ),
    ) -> None:
        self._max_bytes = max_bytes
        self._client = httpx.AsyncClient(
            timeout=timeout_seconds,
            follow_redirects=True,
            headers={"User-Agent": user_agent},
        )

    async def fetch_urls(
        self,
        *,
        urls: list[str],
        max_images: int = 5,
    ) -> tuple[tuple[bytes, str, str], ...]:
        """Return ((bytes, mime_type, source_url), ...) up to ``max_images``."""

        results: list[tuple[bytes, str, str]] = []
        seen: set[str] = set()
        for url in urls:
            cleaned = (url or "").strip()
            if not cleaned or cleaned in seen:
                continue
            seen.add(cleaned)
            fetched = await self._download_one(cleaned)
            if fetched is None:
                continue
            results.append(fetched)
            if len(results) >= max(1, max_images):
                break
        return tuple(results)

    async def _download_one(self, url: str) -> tuple[bytes, str, str] | None:
        try:
            response = await self._client.get(url)
            if response.status_code >= 400:
                logger.warning(
                    "Competitor audit image fetch HTTP %s for %s",
                    response.status_code,
                    url[:120],
                )
                return None
            payload = response.content
            if not payload or len(payload) > self._max_bytes:
                return None
            content_type = (response.headers.get("content-type") or "").split(";")[
                0
            ].strip()
            mime = content_type if content_type.startswith("image/") else ""
            if not mime:
                detected = detect_image_mime(payload)
                mime = detected[0] if detected else "image/jpeg"
            return payload, mime, url
        except httpx.HTTPError as exc:
            logger.warning(
                "Competitor audit image fetch failed for %s: %s",
                url[:120],
                exc,
            )
            return None

    async def aclose(self) -> None:
        await self._client.aclose()
