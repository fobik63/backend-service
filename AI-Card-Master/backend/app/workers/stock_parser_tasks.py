"""Celery workers for the isolated stock-parser micro-module.

Runs outside the FastAPI event loop so scrapes never block the main API.
Nightly Beat (03:00 UTC) dispatches chunked batches of ≤100 tracked SKUs.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Sequence
from datetime import datetime
from typing import Any, TypeVar

from celery import Task

from app.core.config import get_settings
from app.domain.stock_parser import (
    STOCK_PARSER_DEFAULT_CHUNK_SIZE,
    STOCK_PARSER_DEFAULT_KEYSET_BATCH_SIZE,
    ParserMarketplace,
    ParseSkuRequest,
    SkuItemView,
    chunk_sequence,
    nightly_capture_at,
    stabilize_captured_at,
)
from app.infrastructure.celery_app import celery_app
from app.infrastructure.eye_of_god.sku_image_fetcher import SkuCardImageFetcher
from app.infrastructure.eye_of_god_factory import build_eye_of_god_bridge_service
from app.infrastructure.persistence.stock_parser_repository import StockParserRepository
from app.infrastructure.stock_parser_factory import build_stock_parser_service
from app.models.database import SessionLocal
from app.workers.async_runtime import run_worker_async

logger = logging.getLogger(__name__)
T = TypeVar("T")


async def _maybe_trigger_eye_of_god(
    session: Any,
    *,
    marketplace: ParserMarketplace,
    sku: str,
    raw_payload: dict[str, Any] | None = None,
) -> str | None:
    """After a successful parse: if +30%/3d sales spike → enqueue «Глаз Бога»."""

    settings = get_settings()
    if not settings.eye_of_god_enabled:
        return None

    repo = StockParserRepository(session)
    sku_item = await repo.get_sku_item(marketplace=marketplace, article=sku)
    if sku_item is None:
        return None

    image_urls = SkuCardImageFetcher.extract_image_urls_from_raw_payload(
        marketplace.value,
        raw_payload,
    )
    bridge = build_eye_of_god_bridge_service(session, enqueue_trigger=True)
    try:
        job = await bridge.evaluate_and_enqueue_for_sku(
            sku_item=sku_item,
            image_urls=image_urls,
        )
    except Exception:  # noqa: BLE001 — never break the stock parser on AI bridge errors
        logger.exception(
            "Eye-of-God bridge failed marketplace=%s sku=%s",
            marketplace.value,
            sku,
        )
        return None
    if job is None:
        return None
    logger.info(
        "Eye-of-God bridge job_id=%s status=%s sku=%s",
        job.id,
        job.status.value,
        sku,
    )
    return str(job.id)


class StockParserTask(Task):
    """acks_late + reject_on_worker_lost → crash requeues without losing work.

    Snapshot writes are idempotent (unique sku/warehouse/captured_at), so a
    redelivered batch cannot duplicate DB rows.
    """

    autoretry_for = ()
    acks_late = True
    reject_on_worker_lost = True


def _run_async(factory: Callable[[], Awaitable[T]]) -> T:
    """Celery sync boundary; shared pools close on worker_process_shutdown."""

    return run_worker_async(factory)


def _parse_captured_at(value: str | None) -> datetime | None:
    if value is None or not str(value).strip():
        return None
    raw = str(value).strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    return stabilize_captured_at(datetime.fromisoformat(raw))


def _chunk_size() -> int:
    settings = get_settings()
    return max(1, int(settings.stock_parser_chunk_size or STOCK_PARSER_DEFAULT_CHUNK_SIZE))


def _keyset_batch_size() -> int:
    settings = get_settings()
    raw = int(
        settings.stock_parser_keyset_batch_size or STOCK_PARSER_DEFAULT_KEYSET_BATCH_SIZE
    )
    # Keep keyset pages in the audit-recommended 200–500 band.
    return max(200, min(raw, 500))


def build_nightly_batch_payloads(
    items: Sequence[SkuItemView],
    *,
    chunk_size: int = STOCK_PARSER_DEFAULT_CHUNK_SIZE,
) -> list[list[dict[str, Any]]]:
    """Split tracked SKUs into Celery payloads of at most ``chunk_size``."""

    payloads = [
        {
            "marketplace": item.marketplace.value,
            "sku": item.article,
            "product_url": item.product_url,
        }
        for item in items
    ]
    return chunk_sequence(payloads, chunk_size)


@celery_app.task(
    bind=True,
    base=StockParserTask,
    name="stock_parser.dispatch_nightly",
)
def dispatch_nightly_task(self: Task) -> dict[str, Any]:
    """Beat entrypoint: enqueue ≤100-SKU chunk workers for active tracked SKUs.

    Active SKUs are scanned with keyset pagination (``id > last``) so the
    dispatcher never loads the full catalog into RAM at once.
    """

    settings = get_settings()
    captured_at = nightly_capture_at(
        hour=settings.stock_parser_beat_hour_utc,
        minute=settings.stock_parser_beat_minute_utc,
    )
    size = _chunk_size()
    keyset_size = _keyset_batch_size()
    captured_iso = captured_at.isoformat()
    run_date = captured_at.date().isoformat()

    async def _dispatch() -> dict[str, Any]:
        sku_total = 0
        chunk_index = 0
        task_ids: list[str] = []
        pending: list[dict[str, Any]] = []
        last_id = None

        async with SessionLocal() as session:
            repo = StockParserRepository(session)
            while True:
                batch = await repo.list_active_sku_items(
                    after_id=last_id,
                    limit=keyset_size,
                )
                if not batch:
                    break
                for item in batch:
                    pending.append(
                        {
                            "marketplace": item.marketplace.value,
                            "sku": item.article,
                            "product_url": item.product_url,
                        }
                    )
                    if len(pending) >= size:
                        task_id = f"stock_parser.parse_batch.{run_date}.{chunk_index}"
                        async_result = parse_batch_task.apply_async(
                            kwargs={
                                "items": pending,
                                "captured_at": captured_iso,
                            },
                            task_id=task_id,
                        )
                        task_ids.append(str(async_result.id))
                        pending = []
                        chunk_index += 1
                last_id = batch[-1].id
                sku_total += len(batch)
                if len(batch) < keyset_size:
                    break

        if pending:
            task_id = f"stock_parser.parse_batch.{run_date}.{chunk_index}"
            async_result = parse_batch_task.apply_async(
                kwargs={
                    "items": pending,
                    "captured_at": captured_iso,
                },
                task_id=task_id,
            )
            task_ids.append(str(async_result.id))
            chunk_index += 1

        logger.info(
            "Stock parser nightly dispatch sku_total=%s chunks=%s chunk_size=%s "
            "keyset_batch_size=%s captured_at=%s",
            sku_total,
            chunk_index,
            size,
            keyset_size,
            captured_iso,
        )
        return {
            "sku_total": sku_total,
            "chunks": chunk_index,
            "chunk_size": size,
            "keyset_batch_size": keyset_size,
            "captured_at": captured_iso,
            "task_ids": task_ids,
        }

    return _run_async(_dispatch)


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
    captured_at: str | None = None,
) -> dict[str, Any]:
    """Parse a single SKU via marketplace mobile JSON endpoints."""

    capture = _parse_captured_at(captured_at)

    async def _task() -> dict[str, Any]:
        async with SessionLocal() as session:
            service = build_stock_parser_service(session)
            result = await service.parse_sku(
                ParseSkuRequest(
                    marketplace=ParserMarketplace(marketplace),
                    sku=sku,
                    product_url=product_url,
                ),
                captured_at=capture,
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
            if result.ok and result.snapshot is not None:
                eye_job_id = await _maybe_trigger_eye_of_god(
                    session,
                    marketplace=result.marketplace,
                    sku=result.sku,
                    raw_payload=result.snapshot.raw_payload,
                )
                if eye_job_id:
                    payload["eye_of_god_job_id"] = eye_job_id
            return payload

    return _run_async(_task)


@celery_app.task(
    bind=True,
    base=StockParserTask,
    name="stock_parser.parse_batch",
)
def parse_batch_task(
    self: Task,
    items: list[dict[str, Any]],
    captured_at: str | None = None,
) -> dict[str, Any]:
    """Parse a chunk of SKUs (hard-capped to configured chunk size)."""

    size = _chunk_size()
    if len(items) > size:
        logger.warning(
            "Stock parser batch truncated from %s to %s SKUs (OOM guard)",
            len(items),
            size,
        )
        items = items[:size]

    capture = _parse_captured_at(captured_at)

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
            results = await service.parse_many(requests, captured_at=capture)
            ok_count = sum(1 for row in results if row.ok)
            stopped = any(row.parser_stopped for row in results)
            eye_jobs: list[str] = []
            for row in results:
                if not row.ok or row.snapshot is None:
                    continue
                eye_job_id = await _maybe_trigger_eye_of_god(
                    session,
                    marketplace=row.marketplace,
                    sku=row.sku,
                    raw_payload=row.snapshot.raw_payload,
                )
                if eye_job_id:
                    eye_jobs.append(eye_job_id)
            return {
                "total": len(results),
                "ok": ok_count,
                "failed": len(results) - ok_count,
                "parser_stopped": stopped,
                "captured_at": capture.isoformat() if capture else None,
                "eye_of_god_job_ids": eye_jobs,
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
