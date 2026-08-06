"""Celery workers for the isolated stock-parser micro-module.

Runs outside the FastAPI event loop so scrapes never block the main API.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

from celery import Task

from app.domain.stock_parser import ParseSkuRequest, ParserMarketplace
from app.infrastructure.celery_app import celery_app
from app.infrastructure.stock_parser_factory import build_stock_parser_service
from app.models.database import SessionLocal, engine

logger = logging.getLogger(__name__)
T = TypeVar("T")


class StockParserTask(Task):
    """Conservative retries — circuit breaker owns hard-stop semantics."""

    autoretry_for = ()
    acks_late = True
    reject_on_worker_lost = True


def _run_async(factory: Callable[[], Awaitable[T]]) -> T:
    async def _execute() -> T:
        try:
            return await factory()
        finally:
            await engine.dispose()

    return asyncio.run(_execute())


@celery_app.task(
    bind=True,
    base=StockParserTask,
    name="stock_parser.parse_sku",
)
def parse_sku_task(
    self: Task,
    marketplace: str,
    sku: str,
    product_url: str | None = None,
) -> dict[str, Any]:
    """Parse a single SKU via marketplace mobile JSON endpoints."""

    async def _task() -> dict[str, Any]:
        async with SessionLocal() as session:
            service = build_stock_parser_service(session)
            result = await service.parse_sku(
                ParseSkuRequest(
                    marketplace=ParserMarketplace(marketplace),
                    sku=sku,
                    product_url=product_url,
                )
            )
            logger.info(
                "Stock parser sku done marketplace=%s sku=%s ok=%s stopped=%s "
                "health=%s",
                result.marketplace.value,
                result.sku,
                result.ok,
                result.parser_stopped,
                result.health_status.value if result.health_status else None,
            )
            payload: dict[str, Any] = {
                "marketplace": result.marketplace.value,
                "sku": result.sku,
                "ok": result.ok,
                "parser_stopped": result.parser_stopped,
                "health_status": (
                    result.health_status.value if result.health_status else None
                ),
                "error_kind": result.error_kind.value if result.error_kind else None,
                "error_message": result.error_message,
            }
            if result.snapshot is not None:
                payload["snapshot"] = result.snapshot.model_dump(mode="json")
            return payload

    return _run_async(_task)


@celery_app.task(
    bind=True,
    base=StockParserTask,
    name="stock_parser.parse_batch",
)
def parse_batch_task(self: Task, items: list[dict[str, Any]]) -> dict[str, Any]:
    """Parse a list of {marketplace, sku, product_url?} payloads."""

    async def _task() -> dict[str, Any]:
        requests = [
            ParseSkuRequest(
                marketplace=ParserMarketplace(str(item["marketplace"])),
                sku=str(item["sku"]),
                product_url=item.get("product_url"),
            )
            for item in items
        ]
        async with SessionLocal() as session:
            service = build_stock_parser_service(session)
            results = await service.parse_many(requests)
            ok_count = sum(1 for row in results if row.ok)
            stopped = any(row.parser_stopped for row in results)
            return {
                "total": len(results),
                "ok": ok_count,
                "failed": len(results) - ok_count,
                "parser_stopped": stopped,
                "results": [
                    {
                        "marketplace": row.marketplace.value,
                        "sku": row.sku,
                        "ok": row.ok,
                        "parser_stopped": row.parser_stopped,
                        "health_status": (
                            row.health_status.value if row.health_status else None
                        ),
                        "error_kind": (
                            row.error_kind.value if row.error_kind else None
                        ),
                        "total_stock": (
                            row.snapshot.total_stock if row.snapshot else None
                        ),
                    }
                    for row in results
                ],
            }

    return _run_async(_task)
