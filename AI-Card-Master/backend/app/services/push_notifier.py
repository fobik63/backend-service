"""In-app push delivery for Bulk Generation completion alerts."""

from __future__ import annotations

import json
import logging
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.bulk_generation import PushNotificationPayload
from app.models.bulk_generation import UserPushNotification

logger = logging.getLogger(__name__)


class InAppPushNotifier:
    """Persist push payloads so clients can poll unread notifications."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def send(
        self,
        *,
        user_id: UUID,
        payload: PushNotificationPayload,
    ) -> bool:
        try:
            self._session.add(
                UserPushNotification(
                    user_id=user_id,
                    title=payload.title[:200],
                    body=payload.body,
                    data_json=json.dumps(payload.data, ensure_ascii=False),
                )
            )
            await self._session.commit()
            return True
        except Exception:
            logger.warning(
                "In-app push notification failed user_id=%s",
                user_id,
                exc_info=True,
            )
            await self._session.rollback()
            return False
