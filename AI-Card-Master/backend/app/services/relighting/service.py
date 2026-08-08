"""Orchestration: download → relight → S3 → BillingService (5 coins)."""

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

from app.services.billing_service import (
    BillingError,
    BillingNotFoundError,
    BillingService,
    BillingValidationError,
)
from app.services.relighting.dto import (
    RelightingJobResultDTO,
    RelightingPresetName,
    StudioLightDTO,
)
from app.services.relighting.engine import RelightingEngineService
from app.services.relighting.softbox import parse_studio_light_instruction
from app.services.s3_storage import (
    S3UploadResult,
    SelectelS3Storage,
    get_s3_storage,
)

logger = logging.getLogger(__name__)

RELIGHTING_COST_COINS: Final[int] = 5
MAX_DOWNLOAD_BYTES: Final[int] = 20 * 1024 * 1024
DOWNLOAD_TIMEOUT_SECONDS: Final[float] = 25.0

_BLOCKED_HOSTNAMES: Final[frozenset[str]] = frozenset(
    {
        "localhost",
        "metadata.google.internal",
        "metadata.google",
    }
)


class RelightingServiceError(Exception):
    """Base orchestration failure."""


class RelightingValidationError(RelightingServiceError, ValueError):
    """Invalid input (URL, preset, intensity)."""


class RelightingUpstreamError(RelightingServiceError):
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


class RelightingService:
    """Application-facing facade over RelightingEngineService + billing + S3."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        engine: RelightingEngineService | None = None,
        billing: BillingService | None = None,
        storage: SelectelS3Storage | _S3Uploader | None = None,
        http_client: httpx.AsyncClient | None = None,
        cost_coins: int = RELIGHTING_COST_COINS,
    ) -> None:
        self._session = session
        self._engine = engine or RelightingEngineService()
        self._billing = billing or BillingService(session)
        self._storage = storage
        self._http_client = http_client
        self._cost_coins = max(0, int(cost_coins))

    async def process(
        self,
        *,
        user_id: UUID,
        image_url: str,
        preset_name: RelightingPresetName | str,
        shadow_intensity: float = 0.7,
        idempotency_key: str | None = None,
    ) -> RelightingJobResultDTO:
        """Download product image, relight, upload PNG, charge ``cost_coins``."""

        cleaned_url = (image_url or "").strip()
        if not cleaned_url:
            raise RelightingValidationError("image_url must not be empty.")

        intensity = float(shadow_intensity)
        if intensity < 0.0 or intensity > 1.0:
            raise RelightingValidationError(
                "shadow_intensity must be between 0.0 and 1.0."
            )

        try:
            RelightingPresetName(
                preset_name.value
                if isinstance(preset_name, RelightingPresetName)
                else str(preset_name).strip().lower()
            )
        except ValueError as exc:
            allowed = ", ".join(p.value for p in RelightingPresetName)
            raise RelightingValidationError(
                f"Unknown preset_name. Allowed: {allowed}."
            ) from exc

        image_bytes = await self._download_image(cleaned_url)

        # Safe Spend: debit first, refund on processing / storage failure.
        try:
            user = await self._billing.debit_coins_in_transaction(
                user_id=user_id,
                amount=self._cost_coins,
                idempotency_key=idempotency_key,
                response_body={
                    "operation": "relighting",
                    "preset_name": str(
                        preset_name.value
                        if isinstance(preset_name, RelightingPresetName)
                        else preset_name
                    ),
                },
            )
        except BillingValidationError:
            raise
        except BillingNotFoundError:
            raise
        except BillingError as exc:
            raise RelightingServiceError(str(exc)) from exc

        try:
            result = await self._engine.process(
                image_bytes,
                preset_name=preset_name,
                shadow_intensity=intensity,
            )
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
                    "Failed to refund relighting coins for user_id=%s", user_id
                )
            raise

        await self._session.commit()

        return RelightingJobResultDTO(
            result_url=upload.presigned_url or f"s3://{upload.bucket}/{upload.object_key}",
            object_key=upload.object_key,
            preset_name=result.preset_name,
            studio_light=None,
            coins_charged=self._cost_coins,
            new_balance=int(user.ai_coins),
            width=result.width,
            height=result.height,
        )

    async def process_custom(
        self,
        *,
        user_id: UUID,
        image_url: str,
        studio_light: StudioLightDTO,
        idempotency_key: str | None = None,
    ) -> RelightingJobResultDTO:
        """Download product image, apply parametric softbox, upload, charge coins."""

        cleaned_url = (image_url or "").strip()
        if not cleaned_url:
            raise RelightingValidationError("image_url must not be empty.")

        image_bytes = await self._download_image(cleaned_url)

        try:
            user = await self._billing.debit_coins_in_transaction(
                user_id=user_id,
                amount=self._cost_coins,
                idempotency_key=idempotency_key,
                response_body={
                    "operation": "relighting_custom",
                    "studio_light": studio_light.model_dump(mode="json"),
                },
            )
        except BillingValidationError:
            raise
        except BillingNotFoundError:
            raise
        except BillingError as exc:
            raise RelightingServiceError(str(exc)) from exc

        try:
            result = await self._engine.process_custom(
                image_bytes,
                studio_light=studio_light,
            )
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
                    "Failed to refund relighting coins for user_id=%s", user_id
                )
            raise

        await self._session.commit()

        return RelightingJobResultDTO(
            result_url=upload.presigned_url or f"s3://{upload.bucket}/{upload.object_key}",
            object_key=upload.object_key,
            preset_name=None,
            studio_light=studio_light,
            coins_charged=self._cost_coins,
            new_balance=int(user.ai_coins),
            width=result.width,
            height=result.height,
        )

    @staticmethod
    def parse_instruction(instruction: str) -> StudioLightDTO:
        """Convert a natural-language lighting phrase into ``StudioLightDTO``."""

        try:
            return parse_studio_light_instruction(instruction)
        except ValueError as exc:
            raise RelightingValidationError(str(exc)) from exc

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
        object_key = f"relighting/{user_id}/{stamp}_{uuid4().hex}.png"
        result = await storage.upload_bytes(
            object_key=object_key,
            data=png_bytes,
            content_type="image/png",
            presign=True,
        )
        if isinstance(result, S3UploadResult):
            return result
        # Duck-typed test doubles.
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
            raise RelightingValidationError(
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
                raise RelightingValidationError(
                    f"URL did not return an image (content-type={content_type!r})."
                )
            payload = response.content
            if not payload:
                raise RelightingUpstreamError("Downloaded image is empty.")
            if len(payload) > MAX_DOWNLOAD_BYTES:
                raise RelightingValidationError(
                    f"Image exceeds the {MAX_DOWNLOAD_BYTES}-byte download limit."
                )
            return payload
        except httpx.HTTPStatusError as exc:
            raise RelightingUpstreamError(
                f"Failed to download image (HTTP {exc.response.status_code})."
            ) from exc
        except httpx.HTTPError as exc:
            raise RelightingUpstreamError(
                f"Failed to download image: {exc}"
            ) from exc
        finally:
            if owns_client:
                await client.aclose()


async def _assert_public_http_url(url: str, parsed: object) -> None:
    """Reject loopback / link-local / private targets (SSRF shield)."""

    hostname = getattr(parsed, "hostname", None)
    if not hostname:
        raise RelightingValidationError("image_url is missing a hostname.")
    host = str(hostname).strip().lower().rstrip(".")
    if host in _BLOCKED_HOSTNAMES or host.endswith(".localhost"):
        raise RelightingValidationError("image_url targets a blocked host.")

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
            raise RelightingValidationError(
                "image_url must not target a private or reserved IP."
            )
        return
    except OSError:
        pass

    try:
        infos = await asyncio.get_running_loop().getaddrinfo(host, None)
    except OSError as exc:
        raise RelightingUpstreamError(
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
            raise RelightingValidationError(
                "image_url resolves to a private or reserved address."
            )
