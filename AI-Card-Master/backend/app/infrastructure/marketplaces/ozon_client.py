"""Ozon Seller API adapter for product import (draft card creation)."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.domain.export import MarketplacePlatform, MarketplaceSellerError

logger = logging.getLogger(__name__)

OZON_API_BASE = "https://api-seller.ozon.ru"


class OzonSellerClient:
    """Create or update an Ozon product card via /v3/product/import."""

    platform = MarketplacePlatform.OZON

    def __init__(
        self,
        *,
        base_url: str = OZON_API_BASE,
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
        description_category_id = extras.get("description_category_id")
        type_id = extras.get("type_id")
        if not isinstance(description_category_id, int) or description_category_id <= 0:
            raise MarketplaceSellerError(
                "Ozon export requires extras.description_category_id."
            )
        if not isinstance(type_id, int) or type_id <= 0:
            raise MarketplaceSellerError("Ozon export requires extras.type_id.")

        price = str(extras.get("price") or "0")
        vat = str(extras.get("vat") or "0")
        currency_code = str(extras.get("currency_code") or "RUB")
        depth = int(extras.get("depth") or 100)
        width = int(extras.get("width") or 100)
        height = int(extras.get("height") or 100)
        weight = int(extras.get("weight") or 300)

        attributes = extras.get("attributes")
        if not isinstance(attributes, list):
            # Attribute 4191 is commonly used for rich description HTML/text on Ozon.
            # Callers should pass category-specific attribute IDs for production use.
            attributes = [
                {
                    "id": int(extras.get("description_attribute_id") or 4191),
                    "complex_id": 0,
                    "values": [{"dictionary_value_id": 0, "value": description[:6000]}],
                }
            ]
            annotation_id = extras.get("annotation_attribute_id")
            if isinstance(annotation_id, int) and annotation_id > 0:
                attributes.append(
                    {
                        "id": annotation_id,
                        "complex_id": 0,
                        "values": [
                            {
                                "dictionary_value_id": 0,
                                "value": " • ".join(characteristics)[:250],
                            }
                        ],
                    }
                )

        item: dict[str, Any] = {
            "attributes": attributes,
            "description_category_id": description_category_id,
            "type_id": type_id,
            "name": title[:200],
            "offer_id": vendor_code,
            "price": price,
            "vat": vat,
            "currency_code": currency_code,
            "depth": depth,
            "width": width,
            "height": height,
            "dimension_unit": str(extras.get("dimension_unit") or "mm"),
            "weight": weight,
            "weight_unit": str(extras.get("weight_unit") or "g"),
            "images": list(image_urls[:15]),
        }
        if image_urls:
            item["primary_image"] = image_urls[0]

        payload = {"items": [item]}
        headers = {
            "Client-Id": credentials["client_id"],
            "Api-Key": credentials["api_key"],
            "Content-Type": "application/json",
        }

        async with self._http() as client:
            try:
                response = await client.post(
                    f"{self._base_url}/v3/product/import",
                    headers=headers,
                    json=payload,
                )
            except (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError) as exc:
                raise MarketplaceSellerError(
                    f"Ozon API timed out or is unreachable: {exc}"
                ) from exc
            except httpx.HTTPError as exc:
                raise MarketplaceSellerError(
                    f"Ozon API transport error: {exc}"
                ) from exc
            if response.status_code >= 400:
                raise MarketplaceSellerError(
                    f"Ozon product/import failed ({response.status_code}): "
                    f"{response.text[:300]}"
                )
            try:
                body = response.json()
            except ValueError as exc:
                raise MarketplaceSellerError(
                    "Ozon product/import returned non-JSON body."
                ) from exc
            result = body.get("result") or {}
            task_id = result.get("task_id")
            task_id_str = str(task_id) if task_id is not None else None

        return (
            task_id_str,
            vendor_code,
            "Ozon product import task created; the card appears in the seller draft pipeline.",
        )

    def _http(self) -> httpx.AsyncClient:
        if self._client is not None:
            return _NullContextClient(self._client)
        return httpx.AsyncClient(timeout=self._timeout)


class _NullContextClient:
    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client

    async def __aenter__(self) -> httpx.AsyncClient:
        return self._client

    async def __aexit__(self, *args: object) -> None:
        return None
