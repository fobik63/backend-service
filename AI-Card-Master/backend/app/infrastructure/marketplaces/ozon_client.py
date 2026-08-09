"""Ozon Seller API adapter for product import and direct cabinet publish."""

from __future__ import annotations

import logging
from typing import Any
from uuid import uuid4

import httpx

from app.domain.export import MarketplacePlatform, MarketplaceSellerError
from app.domain.marketplace_publish import (
    CredentialValidationResult,
    MarketplacePublishUpstreamError,
    OzonPublishRequest,
    PublishPlatform,
    PublishResultView,
    PublishStatus,
    SellerProductView,
)

logger = logging.getLogger(__name__)

OZON_API_BASE = "https://api-seller.ozon.ru"


class OzonSellerClient:
    """Create or update Ozon products and publish images/description in-cabinet."""

    platform = MarketplacePlatform.OZON
    publish_platform = PublishPlatform.OZON

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
        headers = _ozon_headers(credentials)

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

    async def validate_credentials(
        self, credentials: dict[str, str]
    ) -> CredentialValidationResult:
        """Probe Seller API with warehouse/list (lightweight authenticated call)."""

        client_id = credentials.get("client_id") or credentials.get("ozon_client_id") or ""
        api_key = credentials.get("api_key") or credentials.get("ozon_api_key") or ""
        if not client_id.strip() or not api_key.strip():
            return CredentialValidationResult(
                platform=PublishPlatform.OZON,
                is_valid=False,
                message="Ozon Client-Id and Api-Key are required.",
                error_logs=("missing_ozon_credentials",),
            )

        headers = _ozon_headers(
            {"client_id": client_id.strip(), "api_key": api_key.strip()}
        )
        async with self._http() as client:
            try:
                response = await client.post(
                    f"{self._base_url}/v1/warehouse/list",
                    headers=headers,
                    json={},
                )
            except (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError) as exc:
                return CredentialValidationResult(
                    platform=PublishPlatform.OZON,
                    is_valid=False,
                    message=f"Ozon API unreachable: {exc}",
                    error_logs=(str(exc),),
                )
            except httpx.HTTPError as exc:
                return CredentialValidationResult(
                    platform=PublishPlatform.OZON,
                    is_valid=False,
                    message=f"Ozon transport error: {exc}",
                    error_logs=(str(exc),),
                )

        if response.status_code in {401, 403}:
            return CredentialValidationResult(
                platform=PublishPlatform.OZON,
                is_valid=False,
                message="Ozon rejected Client-Id / Api-Key (unauthorized).",
                error_logs=(f"HTTP {response.status_code}: {response.text[:300]}",),
            )
        if response.status_code >= 400:
            return CredentialValidationResult(
                platform=PublishPlatform.OZON,
                is_valid=False,
                message=f"Ozon credential check failed ({response.status_code}).",
                error_logs=(response.text[:300],),
            )
        return CredentialValidationResult(
            platform=PublishPlatform.OZON,
            is_valid=True,
            message="Ozon Seller API credentials are valid.",
        )

    async def publish(
        self,
        *,
        credentials: dict[str, str],
        request: OzonPublishRequest,
    ) -> PublishResultView:
        """Update images via pictures/import and description via attributes/update."""

        headers = _ozon_headers(credentials)
        error_logs: list[str] = []
        external_task_id: str | None = None
        pending = False

        async with self._http() as client:
            # 1) Description / attributes
            attr_payload = {
                "items": [
                    {
                        "product_id": request.product_id,
                        "attributes": [
                            {
                                "id": request.description_attribute_id,
                                "complex_id": 0,
                                "values": [
                                    {
                                        "dictionary_value_id": 0,
                                        "value": request.description[:10_000],
                                    }
                                ],
                            }
                        ],
                    }
                ]
            }
            try:
                attrs = await client.post(
                    f"{self._base_url}/v1/product/attributes/update",
                    headers=headers,
                    json=attr_payload,
                )
            except (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError) as exc:
                raise MarketplacePublishUpstreamError(
                    f"Ozon attributes/update timed out or is unreachable: {exc}",
                    error_logs=(str(exc),),
                ) from exc
            except httpx.HTTPError as exc:
                raise MarketplacePublishUpstreamError(
                    f"Ozon attributes/update transport error: {exc}",
                    error_logs=(str(exc),),
                ) from exc

            if attrs.status_code >= 400:
                error_logs.append(
                    f"attributes/update HTTP {attrs.status_code}: {attrs.text[:400]}"
                )
                raise MarketplacePublishUpstreamError(
                    "Ozon attributes/update failed.",
                    error_logs=tuple(error_logs),
                )
            try:
                attrs_body = attrs.json()
            except ValueError:
                attrs_body = {}
            task_id = _extract_task_id(attrs_body)
            if task_id:
                external_task_id = task_id
                pending = True

            # 2) Images
            pictures_payload: dict[str, Any] = {
                "product_id": request.product_id,
                "images": list(request.image_urls[:15]),
            }
            if request.image_urls:
                pictures_payload["images360"] = []
            try:
                pictures = await client.post(
                    f"{self._base_url}/v1/product/pictures/import",
                    headers=headers,
                    json=pictures_payload,
                )
            except (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError) as exc:
                raise MarketplacePublishUpstreamError(
                    f"Ozon pictures/import timed out or is unreachable: {exc}",
                    error_logs=(*error_logs, str(exc)),
                ) from exc
            except httpx.HTTPError as exc:
                raise MarketplacePublishUpstreamError(
                    f"Ozon pictures/import transport error: {exc}",
                    error_logs=(*error_logs, str(exc)),
                ) from exc

            if pictures.status_code >= 400:
                error_logs.append(
                    f"pictures/import HTTP {pictures.status_code}: {pictures.text[:400]}"
                )
                raise MarketplacePublishUpstreamError(
                    "Ozon pictures/import failed.",
                    error_logs=tuple(error_logs),
                )
            try:
                pictures_body = pictures.json()
            except ValueError:
                pictures_body = {}
            pic_task = _extract_task_id(pictures_body)
            if pic_task:
                external_task_id = pic_task
                pending = True
            # Ozon often processes pictures asynchronously even without task_id.
            pending = True

        status = PublishStatus.PENDING if pending else PublishStatus.SUCCESS
        return PublishResultView(
            id=uuid4(),
            platform=PublishPlatform.OZON,
            product_id=str(request.product_id),
            status=status,
            message=(
                "Ozon product description and images were submitted. "
                "Seller cabinet processing may take a few minutes."
            ),
            external_task_id=external_task_id,
            error_logs=tuple(error_logs),
        )

    async def list_products(
        self,
        *,
        credentials: dict[str, str],
        limit: int = 50,
    ) -> tuple[SellerProductView, ...]:
        """List products via /v3/product/list + /v3/product/info/list."""

        headers = _ozon_headers(credentials)
        page_limit = max(1, min(limit, 100))
        async with self._http() as client:
            try:
                listed = await client.post(
                    f"{self._base_url}/v3/product/list",
                    headers=headers,
                    json={
                        "filter": {"visibility": "ALL"},
                        "last_id": "",
                        "limit": page_limit,
                    },
                )
            except httpx.HTTPError as exc:
                raise MarketplacePublishUpstreamError(
                    f"Ozon product/list failed: {exc}",
                    error_logs=(str(exc),),
                ) from exc
            if listed.status_code >= 400:
                raise MarketplacePublishUpstreamError(
                    f"Ozon product/list failed ({listed.status_code}).",
                    error_logs=(listed.text[:300],),
                )
            try:
                listed_body = listed.json()
            except ValueError as exc:
                raise MarketplacePublishUpstreamError(
                    "Ozon product/list returned non-JSON body.",
                    error_logs=(listed.text[:300],),
                ) from exc

            result = listed_body.get("result") if isinstance(listed_body, dict) else None
            items_raw = result.get("items") if isinstance(result, dict) else None
            product_ids: list[int] = []
            offer_by_id: dict[int, str] = {}
            if isinstance(items_raw, list):
                for row in items_raw:
                    if not isinstance(row, dict):
                        continue
                    pid = int(row.get("product_id") or 0)
                    if pid <= 0:
                        continue
                    product_ids.append(pid)
                    offer = str(row.get("offer_id") or "").strip()
                    if offer:
                        offer_by_id[pid] = offer
                    if len(product_ids) >= page_limit:
                        break

            if not product_ids:
                return ()

            try:
                info = await client.post(
                    f"{self._base_url}/v3/product/info/list",
                    headers=headers,
                    json={"product_id": product_ids},
                )
            except httpx.HTTPError as exc:
                raise MarketplacePublishUpstreamError(
                    f"Ozon product/info/list failed: {exc}",
                    error_logs=(str(exc),),
                ) from exc
            if info.status_code >= 400:
                # Fallback: return ids without titles when info endpoint fails.
                return tuple(
                    SellerProductView(
                        platform=PublishPlatform.OZON,
                        product_id=str(pid),
                        title=offer_by_id.get(pid) or f"Ozon {pid}",
                        vendor_code=offer_by_id.get(pid),
                    )
                    for pid in product_ids
                )
            try:
                info_body = info.json()
            except ValueError:
                info_body = {}

        info_items = []
        if isinstance(info_body, dict):
            nested = info_body.get("items") or (
                info_body.get("result", {}).get("items")
                if isinstance(info_body.get("result"), dict)
                else None
            )
            if isinstance(nested, list):
                info_items = nested

        by_id: dict[int, dict[str, Any]] = {}
        for row in info_items:
            if isinstance(row, dict):
                pid = int(row.get("id") or row.get("product_id") or 0)
                if pid > 0:
                    by_id[pid] = row

        products: list[SellerProductView] = []
        for pid in product_ids:
            row = by_id.get(pid, {})
            offer = (
                str(row.get("offer_id") or "").strip()
                or offer_by_id.get(pid)
            )
            title = str(row.get("name") or offer or f"Ozon {pid}").strip()
            brand = str(row.get("brand") or "").strip() or None
            products.append(
                SellerProductView(
                    platform=PublishPlatform.OZON,
                    product_id=str(pid),
                    title=title[:300],
                    vendor_code=offer,
                    brand=brand,
                )
            )
        return tuple(products)

    def _http(self) -> httpx.AsyncClient:
        if self._client is not None:
            return _NullContextClient(self._client)
        return httpx.AsyncClient(timeout=self._timeout)


def _ozon_headers(credentials: dict[str, str]) -> dict[str, str]:
    client_id = credentials.get("client_id") or credentials.get("ozon_client_id") or ""
    api_key = credentials.get("api_key") or credentials.get("ozon_api_key") or ""
    return {
        "Client-Id": client_id,
        "Api-Key": api_key,
        "Content-Type": "application/json",
    }


def _extract_task_id(body: Any) -> str | None:
    if not isinstance(body, dict):
        return None
    result = body.get("result")
    if isinstance(result, dict) and result.get("task_id") is not None:
        return str(result["task_id"])
    if body.get("task_id") is not None:
        return str(body["task_id"])
    return None


class _NullContextClient:
    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client

    async def __aenter__(self) -> httpx.AsyncClient:
        return self._client

    async def __aexit__(self, *args: object) -> None:
        return None
