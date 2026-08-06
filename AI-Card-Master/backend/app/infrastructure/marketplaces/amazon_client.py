"""Amazon SP-API Listings Items adapter for draft product submissions."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.domain.export import MarketplacePlatform, MarketplaceSellerError

logger = logging.getLogger(__name__)

LWA_TOKEN_URL = "https://api.amazon.com/auth/o2/token"
DEFAULT_SP_API_BASE = "https://sellingpartnerapi-eu.amazon.com"


class AmazonSellerClient:
    """Submit LISTING_PRODUCT_ONLY via putListingsItem (product-facts draft)."""

    platform = MarketplacePlatform.AMAZON

    def __init__(
        self,
        *,
        sp_api_base_url: str = DEFAULT_SP_API_BASE,
        timeout_seconds: float = 30.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._base_url = sp_api_base_url.rstrip("/")
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
        marketplace_ids = extras.get("marketplace_ids") or ["A1RKKUPIHCS9HS"]
        if isinstance(marketplace_ids, str):
            marketplace_ids = [marketplace_ids]
        product_type = str(extras.get("product_type") or "PRODUCT")
        language_tag = str(extras.get("language_tag") or "en_US")
        marketplace_id = str(marketplace_ids[0])

        bullet_points = [
            {"value": item[:500], "language_tag": language_tag, "marketplace_id": marketplace_id}
            for item in characteristics[:5]
        ]
        attributes: dict[str, Any] = {
            "item_name": [
                {
                    "value": title[:200],
                    "language_tag": language_tag,
                    "marketplace_id": marketplace_id,
                }
            ],
            "product_description": [
                {
                    "value": description[:2000],
                    "language_tag": language_tag,
                    "marketplace_id": marketplace_id,
                }
            ],
            "bullet_point": bullet_points,
        }
        if image_urls:
            attributes["main_product_image_locator"] = [
                {"media_location": image_urls[0], "marketplace_id": marketplace_id}
            ]
            other_images = []
            for index, url in enumerate(image_urls[1:9], start=1):
                other_images.append(
                    {
                        "media_location": url,
                        "marketplace_id": marketplace_id,
                    }
                )
            if other_images:
                attributes["other_product_image_locator_1"] = [other_images[0]]
                for offset, image in enumerate(other_images[1:], start=2):
                    attributes[f"other_product_image_locator_{offset}"] = [image]

        # Allow callers to merge category-specific required attributes.
        extra_attributes = extras.get("attributes")
        if isinstance(extra_attributes, dict):
            attributes.update(extra_attributes)

        payload = {
            "productType": product_type,
            "requirements": "LISTING_PRODUCT_ONLY",
            "attributes": attributes,
        }

        seller_id = credentials["seller_id"]
        async with self._http() as client:
            access_token = await self._exchange_lwa_token(client, credentials)
            params = [("marketplaceIds", mid) for mid in marketplace_ids]
            response = await client.put(
                f"{self._base_url}/listings/2020-09-01/items/{seller_id}/{vendor_code}",
                headers={
                    "x-amz-access-token": access_token,
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
                params=params,
                json=payload,
            )
            if response.status_code >= 400:
                raise MarketplaceSellerError(
                    f"Amazon putListingsItem failed ({response.status_code}): "
                    f"{response.text[:300]}"
                )
            body = response.json()
            status = str(body.get("status") or "ACCEPTED")
            submission_id = body.get("submissionId") or body.get("sku") or vendor_code

        return (
            str(submission_id),
            vendor_code,
            f"Amazon listing submitted as product-only draft (status={status}).",
        )

    async def _exchange_lwa_token(
        self, client: httpx.AsyncClient, credentials: dict[str, str]
    ) -> str:
        response = await client.post(
            LWA_TOKEN_URL,
            data={
                "grant_type": "refresh_token",
                "refresh_token": credentials["refresh_token"],
                "client_id": credentials["lwa_client_id"],
                "client_secret": credentials["lwa_client_secret"],
            },
        )
        if response.status_code >= 400:
            raise MarketplaceSellerError(
                f"Amazon LWA token exchange failed ({response.status_code}): "
                f"{response.text[:300]}"
            )
        body = response.json()
        token = body.get("access_token")
        if not token:
            raise MarketplaceSellerError("Amazon LWA response did not include access_token.")
        return str(token)

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
