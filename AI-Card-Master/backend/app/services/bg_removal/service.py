"""Orchestration: download/upload → rembg → S3 → BillingService (1 coin)."""

from __future__ import annotations

import asyncio
import ipaddress
import logging
import socket
from datetime import UTC, datetime
from typing import Final, Protocol
from urllib.parse import urlparse
from uuid import UUID, uuid4

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.bg_removal.dto import BgRemovalJobResultDTO
from app.services.bg_removal.engine import BackgroundRemovalEngine
from app.services.billing_service import (
    BillingError,
    BillingNotFoundError,
    BillingService,
    BillingValidationError,
)
from app.services.s3_storage import (
    S3UploadResult,
    SelectelS3Storage,
    get_s3_storage,
)

logger = logging.getLogger(__name__)

BG_REMOVAL_COST_COINS: Final[int] = 1
MAX_DOWNLOAD_BYTES: Final[int] = 20 * 1024 * 1024
DOWNLOAD_TIMEOUT_SECONDS: Final[float] = 25.0

_BLOCKED_HOSTNAMES: Final[frozenset[str]] = frozenset(
    {
        "localhost",
        "metadata.google.internal",
        "metadata.google",
    }
)


class BackgroundRemovalServiceError(Exception):
    """Base orchestration failure."""


class BackgroundRemovalValidationError(BackgroundRemovalServiceError, ValueError):
    """Invalid input (empty image, bad URL, etc.)."""


class BackgroundRemovalUpstreamError(BackgroundRemovalServiceError):
    """Image download or storage upstream failure."""


class _S3Uploader(Protocol):
    async def upload_bytes(
        self,
        *,
        object_key: str,
        data: bytes,
        content_type: str,
        presign: bool = True,
        cache_control: str | None = None,
    ) -> object: ...


class BackgroundRemovalService:
    """Application-facing facade over rembg + billing + S3."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        engine: BackgroundRemovalEngine | None = None,
        billing: BillingService | None = None,
        storage: SelectelS3Storage | _S3Uploader | None = None,
        http_client: httpx.AsyncClient | None = None,
        cost_coins: int = BG_REMOVAL_COST_COINS,
    ) -> None:
        self._session = session
        self._engine = engine or BackgroundRemovalEngine()
        self._billing = billing or BillingService(session)
        self._storage = storage
        self._http_client = http_client
        self._cost_coins = max(0, int(cost_coins))

    async def process(
        self,
        *,
        user_id: UUID,
        image_bytes: bytes | None = None,
        image_url: str | None = None,
        idempotency_key: str | None = None,
    ) -> BgRemovalJobResultDTO:
        """Cut out the product, upload PNG, charge ``cost_coins`` (Safe Spend)."""

        payload = await self._resolve_image_bytes(
            image_bytes=image_bytes,
            image_url=image_url,
        )

        # Safe Spend: debit first, refund on processing / storage failure.
        try:
            user = await self._billing.debit_coins_in_transaction(
                user_id=user_id,
                amount=self._cost_coins,
                idempotency_key=idempotency_key,
                response_body={"operation": "bg_removal"},
            )
        except BillingValidationError:
            raise
        except BillingNotFoundError:
            raise
        except BillingError as exc:
            raise BackgroundRemovalServiceError(str(exc)) from exc

        try:
            result = await self._engine.process(payload)
            upload = await self._upload_result(
                user_id=user_id,
                png_bytes=result.image_png,
            )
        except Exception:
            try:
                await self._billing.refund_coins_in_transaction(
                    user_id=user_id,
                    amount=self._cost_coins,
                )
            except BillingError:
                logger.exception(
                    "Failed to refund bg_removal coins for user_id=%s", user_id
                )
            raise

        await self._session.commit()

        cdn_url = upload.presigned_url or f"s3://{upload.bucket}/{upload.object_key}"
        return BgRemovalJobResultDTO(
            cdn_url=cdn_url,
            object_key=upload.object_key,
            coins_charged=self._cost_coins,
            new_balance=int(user.ai_coins),
            width=result.width,
            height=result.height,
        )

    async def _resolve_image_bytes(
        self,
        *,
        image_bytes: bytes | None,
        image_url: str | None,
    ) -> bytes:
        has_bytes = bool(image_bytes)
        cleaned_url = (image_url or "").strip()
        has_url = bool(cleaned_url)

        if has_bytes and has_url:
            raise BackgroundRemovalValidationError(
                "Provide either image file bytes or image_url, not both."
            )
        if not has_bytes and not has_url:
            raise BackgroundRemovalValidationError(
                "Provide an image file or image_url."
            )

        if has_bytes:
            assert image_bytes is not None
            if len(image_bytes) > MAX_DOWNLOAD_BYTES:
                raise BackgroundRemovalValidationError(
                    f"Image exceeds the {MAX_DOWNLOAD_BYTES}-byte upload limit."
                )
            return bytes(image_bytes)

        return await self._download_image(cleaned_url)

    async def _upload_result(
        self,
        *,
        user_id: UUID,
        png_bytes: bytes,
    ) -> S3UploadResult:
        storage = self._storage
        if storage is None:
            storage = get_s3_storage()
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        object_key = f"bg_removal/{user_id}/{stamp}_{uuid4().hex}.png"
        result = await storage.upload_bytes(
            object_key=object_key,
            data=png_bytes,
            content_type="image/png",
            presign=True,
        )
        if isinstance(result, S3UploadResult):
            return result
        return S3UploadResult(
            bucket=str(getattr(result, "bucket", "test-bucket")),
            object_key=str(getattr(result, "object_key", object_key)),
            etag=getattr(result, "etag", None),
            presigned_url=str(getattr(result, "presigned_url", "")),
        )

    async def _download_image(self, url: str) -> bytes:
        parsed = urlparse(url)
        scheme = (parsed.scheme or "").lower()
        if scheme not in {"http", "https"}:
            raise BackgroundRemovalValidationError(
                "image_url must be an http(s) URL."
            )
        await _assert_public_http_url(url, parsed)

        client = self._http_client
        owns_client = False
        if client is None:
            client = httpx.AsyncClient(
                timeout=httpx.Timeout(DOWNLOAD_TIMEOUT_SECONDS),
                follow_redirects=True,
            )
            owns_client = True

        try:
            response = await client.get(url)
            response.raise_for_status()
            content_type = (response.headers.get("content-type") or "").lower()
            if content_type and not any(
                token in content_type
                for token in ("image/", "octet-stream", "binary")
            ):
                raise BackgroundRemovalValidationError(
                    f"URL did not return an image (content-type={content_type!r})."
                )
            payload = response.content
            if not payload:
                raise BackgroundRemovalUpstreamError("Downloaded image is empty.")
            if len(payload) > MAX_DOWNLOAD_BYTES:
                raise BackgroundRemovalValidationError(
                    f"Image exceeds the {MAX_DOWNLOAD_BYTES}-byte download limit."
                )
            return payload
        except httpx.HTTPStatusError as exc:
            raise BackgroundRemovalUpstreamError(
                f"Failed to download image (HTTP {exc.response.status_code})."
            ) from exc
        except httpx.HTTPError as exc:
            raise BackgroundRemovalUpstreamError(
                f"Failed to download image: {exc}"
            ) from exc
        finally:
            if owns_client:
                await client.aclose()


async def _assert_public_http_url(url: str, parsed: object) -> None:
    """Reject loopback / link-local / private targets (SSRF shield)."""

    hostname = getattr(parsed, "hostname", None)
    if not hostname:
        raise BackgroundRemovalValidationError("image_url is missing a hostname.")
    host = str(hostname).strip().lower().rstrip(".")
    if host in _BLOCKED_HOSTNAMES or host.endswith(".localhost"):
        raise BackgroundRemovalValidationError("image_url targets a blocked host.")

    try:
        packed = socket.inet_pton(
            socket.AF_INET6 if ":" in host else socket.AF_INET, host
        )
        ip = ipaddress.ip_address(packed)
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
        ):
            raise BackgroundRemovalValidationError(
                "image_url must not target a private or reserved IP."
            )
        return
    except OSError:
        pass

    try:
        infos = await asyncio.get_running_loop().getaddrinfo(host, None)
    except OSError as exc:
        raise BackgroundRemovalUpstreamError(
            f"Cannot resolve image_url host {host!r}."
        ) from exc

    for _family, _type, _proto, _canon, sockaddr in infos:
        ip_str = sockaddr[0]
        ip = ipaddress.ip_address(ip_str)
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
        ):
            raise BackgroundRemovalValidationError(
                "image_url resolves to a private or reserved address."
            )

