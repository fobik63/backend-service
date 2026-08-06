"""Wildberries Content API adapter for draft product card creation."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.domain.export import MarketplacePlatform, MarketplaceSellerError

logger = logging.getLogger(__name__)

WB_CONTENT_BASE = "https://content-api.wildberries.ru"


class WildberriesSellerClient:
    """Create WB product cards (async draft) and attach media by public links."""

    platform = MarketplacePlatform.WILDBERRIES

    def __init__(
        self,
        *,
        base_url: str = WB_CONTENT_BASE,
        timeout_seconds: float = 30.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout_seconds
        self._client = client

    async def create_product_draft(
        self,
        *,
        credentials: dict[str, str],
        vendor_code: str,
        title: str,
        description: str,
        characteristics: tuple[str, ...],
        image_urls: tuple[str, ...],
        extras: dict[str, Any],
    ) -> tuple[str | None, str | None, str]:
        token = credentials["api_token"]
        subject_id = extras.get("subject_id")
        if not isinstance(subject_id, int) or subject_id <= 0:
            raise MarketplaceSellerError(
                "Wildberries export requires extras.subject_id (WB subject / category id)."
            )

        brand = str(extras.get("brand") or "NoBrand")
        dimensions = extras.get("dimensions") or {
            "length": 10,
            "width": 10,
            "height": 10,
            "weightBrutto": 0.3,
        }
        sizes = extras.get("sizes") or [
            {
                "techSize": str(extras.get("tech_size") or "0"),
                "wbSize": str(extras.get("wb_size") or ""),
                "price": int(extras.get("price") or 0),
                "skus": list(extras.get("skus") or [vendor_code]),
            }
        ]

        # Free-form advantages are stored as a single text characteristic when
        # the caller did not supply structured WB charc IDs.
        wb_characteristics = extras.get("characteristics")
        if not isinstance(wb_characteristics, list):
            wb_characteristics = [
                {"id": int(extras.get("advantages_charc_id") or 0), "value": list(characteristics)}
            ]
            if wb_characteristics[0]["id"] <= 0:
                wb_characteristics = []

        payload = [
            {
                "subjectID": subject_id,
                "variants": [
                    {
                        "vendorCode": vendor_code,
                        "title": title[:100],
                        "description": description[:5000],
                        "brand": brand,
                        "dimensions": dimensions,
                        "characteristics": wb_characteristics,
                        "sizes": sizes,
                    }
                ],
            }
        ]

        async with self._http() as client:
            try:
                upload = await client.post(
                    f"{self._base_url}/content/v2/cards/upload",
                    headers=_wb_headers(token),
                    json=payload,
                )
            except (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError) as exc:
                raise MarketplaceSellerError(
                    f"Wildberries API timed out or is unreachable: {exc}"
                ) from exc
            except httpx.HTTPError as exc:
                raise MarketplaceSellerError(
                    f"Wildberries API transport error: {exc}"
                ) from exc
            if upload.status_code >= 400:
                raise MarketplaceSellerError(
                    f"Wildberries cards/upload failed ({upload.status_code}): "
                    f"{upload.text[:300]}"
                )
            try:
                body = upload.json()
            except ValueError as exc:
                raise MarketplaceSellerError(
                    "Wildberries cards/upload returned non-JSON body."
                ) from exc
            if body.get("error"):
                raise MarketplaceSellerError(
                    f"Wildberries cards/upload error: {body.get('errorText') or body}"
                )

            # Media requires nmID; card creation is async. Callers may pass nmID
            # when re-exporting media onto an already-created card.
            nm_id = extras.get("nm_id")
            if isinstance(nm_id, int) and nm_id > 0 and image_urls:
                try:
                    media = await client.post(
                        f"{self._base_url}/content/v3/media/save",
                        headers=_wb_headers(token),
                        json={"nmId": nm_id, "data": list(image_urls)},
                    )
                except (
                    httpx.TimeoutException,
                    httpx.NetworkError,
                    httpx.RemoteProtocolError,
                ) as exc:
                    raise MarketplaceSellerError(
                        f"Wildberries media/save timed out or is unreachable: {exc}"
                    ) from exc
                except httpx.HTTPError as exc:
                    raise MarketplaceSellerError(
                        f"Wildberries media/save transport error: {exc}"
                    ) from exc
                if media.status_code >= 400:
                    raise MarketplaceSellerError(
                        f"Wildberries media/save failed ({media.status_code}): "
                        f"{media.text[:300]}"
                    )

        return (
            None,
            vendor_code,
            "Wildberries card queued for creation (draft sync may take up to 30 minutes). "
            "Attach photos via media/save once nmID is available.",
        )

    def _http(self) -> httpx.AsyncClient:
        if self._client is not None:
            return _NullContextClient(self._client)
        return httpx.AsyncClient(timeout=self._timeout)


def _wb_headers(token: str) -> dict[str, str]:
    return {
        "Authorization": token,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


class _NullContextClient:
    """Allow injecting a shared AsyncClient without closing it on exit."""

    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client

    async def __aenter__(self) -> httpx.AsyncClient:
        return self._client

    async def __aexit__(self, *args: object) -> None:
        return None
