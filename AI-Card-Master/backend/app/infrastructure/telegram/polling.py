"""Long-polling runner for the product Telegram bot."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from app.infrastructure.telegram.bot_client import TelegramBotApiClient

logger = logging.getLogger(__name__)

UpdateHandler = Callable[[dict[str, Any]], Awaitable[None]]


class TelegramLongPollingRunner:
    """Background getUpdates loop (used when webhook URL is not configured)."""

    def __init__(
        self,
        client: TelegramBotApiClient,
        handler: UpdateHandler,
        *,
        poll_timeout_seconds: int = 25,
    ) -> None:
        self._client = client
        self._handler = handler
        self._poll_timeout = poll_timeout_seconds
        self._task: asyncio.Task[None] | None = None
        self._stopped = asyncio.Event()
        self._offset: int | None = None

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    def start(self) -> None:
        if self.running or not self._client.enabled:
            return
        self._stopped.clear()
        self._task = asyncio.create_task(self._run(), name="telegram-bot-polling")

    async def stop(self) -> None:
        self._stopped.set()
        task = self._task
        self._task = None
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    async def _run(self) -> None:
        logger.info("Telegram long polling started")
        try:
            await self._client.delete_webhook(drop_pending_updates=False)
            while not self._stopped.is_set():
                updates = await self._client.get_updates(
                    offset=self._offset,
                    timeout=self._poll_timeout,
                )
                for update in updates:
                    if not isinstance(update, dict):
                        continue
                    update_id = update.get("update_id")
                    if isinstance(update_id, int):
                        self._offset = update_id + 1
                    try:
                        await self._handler(update)
                    except Exception:
                        logger.exception("Telegram update handler failed")
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Telegram long polling crashed")
        finally:
            logger.info("Telegram long polling stopped")
