"""Wildberries Content API adapter for draft creation and direct cabinet publish."""

from __future__ import annotations

import logging
from typing import Any
from uuid import uuid4

import httpx

from app.domain.export import MarketplacePlatform, MarketplaceSellerError
from app.domain.marketplace_publish import (
    CredentialValidationResult,
    MarketplacePublishUpstreamError,
    PublishPlatform,
    PublishResultView,
    PublishStatus,
    SellerProductView,
    WbPublishRequest,
)

logger = logging.getLogger(__name__)

WB_CONTENT_BASE = "https://content-api.wildberries.ru"


class WildberriesSellerClient:
    """Create WB product cards and publish media/SEO onto existing nmIDs."""

    platform = MarketplacePlatform.WILDBERRIES
    publish_platform = PublishPlatform.WILDBERRIES

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

    async def validate_credentials(
        self, credentials: dict[str, str]
    ) -> CredentialValidationResult:
        """Probe Content API with a minimal cards/list request."""

        token = credentials.get("api_token") or credentials.get("wb_api_token") or ""
        if not token.strip():
            return CredentialValidationResult(
                platform=PublishPlatform.WILDBERRIES,
                is_valid=False,
                message="Wildberries API token is empty.",
                error_logs=("missing_api_token",),
            )

        payload = {
            "settings": {
                "cursor": {"limit": 1},
                "filter": {"withPhoto": -1},
            }
        }
        async with self._http() as client:
            try:
                response = await client.post(
                    f"{self._base_url}/content/v2/get/cards/list",
                    headers=_wb_headers(token),
                    json=payload,
                )
            except (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError) as exc:
                return CredentialValidationResult(
                    platform=PublishPlatform.WILDBERRIES,
                    is_valid=False,
                    message=f"Wildberries API unreachable: {exc}",
                    error_logs=(str(exc),),
                )
            except httpx.HTTPError as exc:
                return CredentialValidationResult(
                    platform=PublishPlatform.WILDBERRIES,
                    is_valid=False,
                    message=f"Wildberries transport error: {exc}",
                    error_logs=(str(exc),),
                )

        if response.status_code in {401, 403}:
            return CredentialValidationResult(
                platform=PublishPlatform.WILDBERRIES,
                is_valid=False,
                message="Wildberries rejected the API token (unauthorized).",
                error_logs=(f"HTTP {response.status_code}: {response.text[:300]}",),
            )
        if response.status_code >= 400:
            return CredentialValidationResult(
                platform=PublishPlatform.WILDBERRIES,
                is_valid=False,
                message=f"Wildberries credential check failed ({response.status_code}).",
                error_logs=(response.text[:300],),
            )
        try:
            body = response.json()
        except ValueError:
            return CredentialValidationResult(
                platform=PublishPlatform.WILDBERRIES,
                is_valid=False,
                message="Wildberries returned a non-JSON body during validation.",
                error_logs=(response.text[:300],),
            )
        if body.get("error"):
            return CredentialValidationResult(
                platform=PublishPlatform.WILDBERRIES,
                is_valid=False,
                message=str(body.get("errorText") or body.get("error")),
                error_logs=(str(body)[:300],),
            )
        return CredentialValidationResult(
            platform=PublishPlatform.WILDBERRIES,
            is_valid=True,
            message="Wildberries API token is valid.",
        )

    async def publish(
        self,
        *,
        credentials: dict[str, str],
        request: WbPublishRequest,
    ) -> PublishResultView:
        """Update media via /content/v3/media/save and SEO via /content/v2/cards/update."""

        token = credentials.get("api_token") or credentials.get("wb_api_token") or ""
        if not token.strip():
            raise MarketplacePublishUpstreamError(
                "Wildberries API token is not configured.",
                error_logs=("missing_api_token",),
            )

        error_logs: list[str] = []
        external_task_id: str | None = None
        pending = False

        async with self._http() as client:
            card = await self._fetch_card(client, token=token, nm_id=request.nm_id)
            if card is None:
                raise MarketplacePublishUpstreamError(
                    f"Wildberries card nmID={request.nm_id} was not found in the seller cabinet.",
                    error_logs=(f"card_not_found:{request.nm_id}",),
                )

            update_payload = _build_card_update_payload(
                card,
                description=request.seo_text,
                title=request.title,
                vendor_code=request.vendor_code,
            )
            try:
                update = await client.post(
                    f"{self._base_url}/content/v2/cards/update",
                    headers=_wb_headers(token),
                    json=[update_payload],
                )
            except (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError) as exc:
                raise MarketplacePublishUpstreamError(
                    f"Wildberries cards/update timed out or is unreachable: {exc}",
                    error_logs=(str(exc),),
                ) from exc
            except httpx.HTTPError as exc:
                raise MarketplacePublishUpstreamError(
                    f"Wildberries cards/update transport error: {exc}",
                    error_logs=(str(exc),),
                ) from exc

            if update.status_code >= 400:
                error_logs.append(
                    f"cards/update HTTP {update.status_code}: {update.text[:400]}"
                )
                raise MarketplacePublishUpstreamError(
                    "Wildberries cards/update failed.",
                    error_logs=tuple(error_logs),
                )
            try:
                update_body = update.json()
            except ValueError as exc:
                raise MarketplacePublishUpstreamError(
                    "Wildberries cards/update returned non-JSON body.",
                    error_logs=(update.text[:300],),
                ) from exc
            if update_body.get("error"):
                error_logs.append(str(update_body.get("errorText") or update_body))
                raise MarketplacePublishUpstreamError(
                    "Wildberries cards/update rejected the payload.",
                    error_logs=tuple(error_logs),
                )
            pending = True

            try:
                media = await client.post(
                    f"{self._base_url}/content/v3/media/save",
                    headers=_wb_headers(token),
                    json={"nmId": request.nm_id, "data": list(request.image_urls)},
                )
            except (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError) as exc:
                raise MarketplacePublishUpstreamError(
                    f"Wildberries media/save timed out or is unreachable: {exc}",
                    error_logs=(*error_logs, str(exc)),
                ) from exc
            except httpx.HTTPError as exc:
                raise MarketplacePublishUpstreamError(
                    f"Wildberries media/save transport error: {exc}",
                    error_logs=(*error_logs, str(exc)),
                ) from exc

            if media.status_code >= 400:
                error_logs.append(
                    f"media/save HTTP {media.status_code}: {media.text[:400]}"
                )
                raise MarketplacePublishUpstreamError(
                    "Wildberries media/save failed.",
                    error_logs=tuple(error_logs),
                )
            try:
                media_body = media.json()
            except ValueError:
                media_body = {}
            if isinstance(media_body, dict) and media_body.get("error"):
                error_logs.append(str(media_body.get("errorText") or media_body))
                raise MarketplacePublishUpstreamError(
                    "Wildberries media/save rejected the image URLs.",
                    error_logs=tuple(error_logs),
                )
            pending = True

        status = PublishStatus.PENDING if pending else PublishStatus.SUCCESS
        return PublishResultView(
            id=uuid4(),
            platform=PublishPlatform.WILDBERRIES,
            product_id=str(request.nm_id),
            status=status,
            message=(
                "Wildberries card description and media were queued for update. "
                "Cabinet sync may take several minutes."
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
        """List seller cards via content/v2/get/cards/list."""

        token = credentials.get("api_token") or credentials.get("wb_api_token") or ""
        if not token.strip():
            raise MarketplacePublishUpstreamError(
                "Wildberries API token is not configured.",
                error_logs=("missing_api_token",),
            )
        page_limit = max(1, min(limit, 100))
        payload = {
            "settings": {
                "cursor": {"limit": page_limit},
                "filter": {"withPhoto": -1},
            }
        }
        async with self._http() as client:
            try:
                response = await client.post(
                    f"{self._base_url}/content/v2/get/cards/list",
                    headers=_wb_headers(token),
                    json=payload,
                )
            except httpx.HTTPError as exc:
                raise MarketplacePublishUpstreamError(
                    f"Wildberries cards/list failed: {exc}",
                    error_logs=(str(exc),),
                ) from exc
        if response.status_code >= 400:
            raise MarketplacePublishUpstreamError(
                f"Wildberries cards/list failed ({response.status_code}).",
                error_logs=(response.text[:300],),
            )
        try:
            body = response.json()
        except ValueError as exc:
            raise MarketplacePublishUpstreamError(
                "Wildberries cards/list returned non-JSON body.",
                error_logs=(response.text[:300],),
            ) from exc
        cards = body.get("cards") if isinstance(body, dict) else None
        if not isinstance(cards, list):
            return ()
        items: list[SellerProductView] = []
        for card in cards:
            if not isinstance(card, dict):
                continue
            nm_id = int(card.get("nmID") or card.get("nmId") or 0)
            if nm_id <= 0:
                continue
            vendor = str(card.get("vendorCode") or "").strip() or None
            brand = str(card.get("brand") or "").strip() or None
            title = str(card.get("title") or vendor or f"nmID {nm_id}").strip()
            items.append(
                SellerProductView(
                    platform=PublishPlatform.WILDBERRIES,
                    product_id=str(nm_id),
                    title=title[:300],
                    vendor_code=vendor,
                    brand=brand,
                )
            )
            if len(items) >= page_limit:
                break
        return tuple(items)

    async def _fetch_card(
        self,
        client: httpx.AsyncClient,
        *,
        token: str,
        nm_id: int,
    ) -> dict[str, Any] | None:
        payload = {
            "settings": {
                "cursor": {"limit": 100},
                "filter": {"textSearch": str(nm_id), "withPhoto": -1},
            }
        }
        try:
            response = await client.post(
                f"{self._base_url}/content/v2/get/cards/list",
                headers=_wb_headers(token),
                json=payload,
            )
        except httpx.HTTPError as exc:
            raise MarketplacePublishUpstreamError(
                f"Wildberries cards/list failed: {exc}",
                error_logs=(str(exc),),
            ) from exc
        if response.status_code >= 400:
            raise MarketplacePublishUpstreamError(
                f"Wildberries cards/list failed ({response.status_code}).",
                error_logs=(response.text[:300],),
            )
        try:
            body = response.json()
        except ValueError as exc:
            raise MarketplacePublishUpstreamError(
                "Wildberries cards/list returned non-JSON body.",
                error_logs=(response.text[:300],),
            ) from exc
        cards = body.get("cards") if isinstance(body, dict) else None
        if not isinstance(cards, list):
            return None
        for card in cards:
            if not isinstance(card, dict):
                continue
            if int(card.get("nmID") or card.get("nmId") or 0) == nm_id:
                return card
        return None

    def _http(self) -> httpx.AsyncClient:
        if self._client is not None:
            return _NullContextClient(self._client)
        return httpx.AsyncClient(timeout=self._timeout)


def _build_card_update_payload(
    card: dict[str, Any],
    *,
    description: str,
    title: str | None,
    vendor_code: str | None,
) -> dict[str, Any]:
    """Merge SEO fields into the existing card object for cards/update."""

    nm_id = int(card.get("nmID") or card.get("nmId") or 0)
    payload: dict[str, Any] = {
        "nmID": nm_id,
        "vendorCode": vendor_code or str(card.get("vendorCode") or ""),
        "brand": str(card.get("brand") or ""),
        "title": (title or str(card.get("title") or ""))[:100],
        "description": description[:5000],
        "dimensions": card.get("dimensions")
        or {"length": 10, "width": 10, "height": 10, "weightBrutto": 0.3},
        "characteristics": card.get("characteristics") or [],
        "sizes": card.get("sizes") or [],
    }
    if card.get("imtID") is not None:
        payload["imtID"] = card["imtID"]
    return payload


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
