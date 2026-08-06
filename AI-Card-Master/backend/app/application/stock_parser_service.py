"""Application service for isolated WB/Ozon stock parsing (plan §72).

Strictly separated from FastAPI: no Request/Response imports.
Circuit breaker stops scrapes after schema drift or 5 consecutive hard errors.
"""

from __future__ import annotations

import logging
import traceback
from typing import Mapping

from app.application.ports.stock_parser import (
    MarketplaceMobileParserPort,
    ParserAlertPort,
    StockParserPersistencePort,
)
from app.domain.stock_parser import (
    CIRCUIT_BREAKER_THRESHOLD,
    ParseSkuRequest,
    ParserErrorKind,
    ParserHealthStatus,
    ParserMarketplace,
    ParserRunResult,
)
from app.infrastructure.stock_parser.exceptions import (
    ParserStoppedError,
    StockParserError,
)

logger = logging.getLogger(__name__)


class StockParserService:
    """Orchestrate mobile JSON scrapes + health / Telegram circuit breaker."""

    def __init__(
        self,
        persistence: StockParserPersistencePort,
        parsers: Mapping[ParserMarketplace, MarketplaceMobileParserPort],
        alerts: ParserAlertPort | None = None,
        *,
        circuit_breaker_threshold: int = CIRCUIT_BREAKER_THRESHOLD,
    ) -> None:
        self._persistence = persistence
        self._parsers = dict(parsers)
        self._alerts = alerts
        self._threshold = max(1, circuit_breaker_threshold)

    async def parse_sku(self, request: ParseSkuRequest) -> ParserRunResult:
        """Fetch one SKU; on repeated failures mark broken and alert admin."""

        health = await self._persistence.get_or_create_health(
            marketplace=request.marketplace
        )
        if health.status in {
            ParserHealthStatus.BROKEN,
            ParserHealthStatus.DISABLED,
        }:
            logger.warning(
                "Stock parser refused (status=%s) marketplace=%s sku=%s",
                health.status.value,
                request.marketplace.value,
                request.sku,
            )
            return ParserRunResult(
                marketplace=request.marketplace,
                sku=request.sku,
                ok=False,
                error_kind=ParserErrorKind.UNKNOWN,
                error_message=(
                    f"Parser is {health.status.value}; refusing further requests "
                    "to protect the main API."
                ),
                parser_stopped=True,
                health_status=health.status,
            )

        parser = self._parsers.get(request.marketplace)
        if parser is None:
            return ParserRunResult(
                marketplace=request.marketplace,
                sku=request.sku,
                ok=False,
                error_kind=ParserErrorKind.UNKNOWN,
                error_message=f"No mobile parser wired for {request.marketplace.value}",
                parser_stopped=False,
                health_status=health.status,
            )

        try:
            snapshot = await parser.fetch_sku(request)
        except StockParserError as exc:
            return await self._handle_failure(
                request=request,
                error_kind=exc.kind,
                error_message=str(exc),
                exc=exc,
            )
        except KeyError as exc:
            return await self._handle_failure(
                request=request,
                error_kind=ParserErrorKind.KEY_ERROR,
                error_message=f"KeyError: {exc}",
                exc=exc,
            )
        except Exception as exc:  # noqa: BLE001 — isolate scraper from API process
            return await self._handle_failure(
                request=request,
                error_kind=ParserErrorKind.UNKNOWN,
                error_message=f"{type(exc).__name__}: {exc}",
                exc=exc,
            )

        health = await self._persistence.record_success(
            marketplace=request.marketplace
        )
        return ParserRunResult(
            marketplace=request.marketplace,
            sku=request.sku,
            ok=True,
            snapshot=snapshot,
            parser_stopped=False,
            health_status=health.status,
        )

    async def parse_many(
        self, requests: list[ParseSkuRequest]
    ) -> list[ParserRunResult]:
        """Parse a batch; stop marketplace early once circuit trips."""

        results: list[ParserRunResult] = []
        stopped: set[ParserMarketplace] = set()
        for request in requests:
            if request.marketplace in stopped:
                results.append(
                    ParserRunResult(
                        marketplace=request.marketplace,
                        sku=request.sku,
                        ok=False,
                        error_kind=ParserErrorKind.UNKNOWN,
                        error_message="Skipped: parser already stopped in this batch.",
                        parser_stopped=True,
                        health_status=ParserHealthStatus.BROKEN,
                    )
                )
                continue
            result = await self.parse_sku(request)
            results.append(result)
            if result.parser_stopped or result.health_status is ParserHealthStatus.BROKEN:
                stopped.add(request.marketplace)
        return results

    async def get_health(self, marketplace: ParserMarketplace):
        return await self._persistence.get_or_create_health(marketplace=marketplace)

    async def reenable(self, marketplace: ParserMarketplace):
        """Ops path: clear broken after marketplace schema / proxy fix."""

        return await self._persistence.set_status(
            marketplace=marketplace,
            status=ParserHealthStatus.HEALTHY,
        )

    async def _handle_failure(
        self,
        *,
        request: ParseSkuRequest,
        error_kind: ParserErrorKind,
        error_message: str,
        exc: BaseException,
    ) -> ParserRunResult:
        traceback_text = "".join(
            traceback.format_exception(type(exc), exc, exc.__traceback__)
        )
        # Schema drift (missing stocks etc.) trips immediately; hard HTTP/KeyError
        # accumulate toward the consecutive-error threshold.
        immediate_break = error_kind in {
            ParserErrorKind.SCHEMA_DRIFT,
            ParserErrorKind.KEY_ERROR,
        }
        health = await self._persistence.get_or_create_health(
            marketplace=request.marketplace
        )
        next_count = health.consecutive_errors + 1
        mark_broken = immediate_break or next_count >= self._threshold

        health = await self._persistence.record_failure(
            marketplace=request.marketplace,
            error_kind=error_kind,
            error_message=error_message,
            traceback_text=traceback_text,
            mark_broken=mark_broken,
        )

        if mark_broken and health.status is ParserHealthStatus.BROKEN:
            await self._notify_broken(health=health, traceback_text=traceback_text)
            logger.error(
                "Stock parser marked BROKEN marketplace=%s kind=%s errors=%s",
                request.marketplace.value,
                error_kind.value,
                health.consecutive_errors,
            )

        return ParserRunResult(
            marketplace=request.marketplace,
            sku=request.sku,
            ok=False,
            error_kind=error_kind,
            error_message=error_message,
            parser_stopped=health.status
            in {ParserHealthStatus.BROKEN, ParserHealthStatus.DISABLED},
            health_status=health.status,
        )

    async def _notify_broken(self, *, health, traceback_text: str) -> None:
        if self._alerts is None:
            return
        if health.alert_sent_at is not None and health.broken_at is not None:
            # Avoid alert spam for the same unbroken incident window.
            if health.alert_sent_at >= health.broken_at:
                return
        sent = await self._alerts.send_broken_alert(
            marketplace=health.marketplace,
            error_kind=health.last_error_kind or ParserErrorKind.UNKNOWN,
            error_message=health.last_error_message or "unknown",
            traceback_text=traceback_text or health.last_traceback or "",
            consecutive_errors=health.consecutive_errors,
            health_id=health.id,
        )
        if sent:
            await self._persistence.mark_alert_sent(marketplace=health.marketplace)


class StockParserNotConfiguredError(RuntimeError):
    """Raised when a marketplace mobile client cannot be constructed."""


# Re-export for workers that prefer a domain-ish name.
__all__ = [
    "ParserStoppedError",
    "StockParserNotConfiguredError",
    "StockParserService",
]
