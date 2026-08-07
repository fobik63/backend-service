"""WebSocket live progress for 3D generation and 360° video tasks."""

from __future__ import annotations

import asyncio
import logging
from uuid import UUID

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.security import InvalidTokenError, decode_and_validate_token
from app.domain.three_d import (
    TERMINAL_THREE_D_STATUSES,
    ThreeDProgressSnapshot,
)
from app.domain.three_d_video import (
    TERMINAL_THREE_D_VIDEO_STATUSES,
    ThreeDVideoProgressSnapshot,
)
from app.infrastructure.three_d_factory import build_three_d_service
from app.infrastructure.three_d_progress_cache import RedisThreeDProgressCache
from app.infrastructure.three_d_video_factory import build_three_d_video_render_service
from app.infrastructure.three_d_video_progress_cache import RedisThreeDVideoProgressCache
from app.models.database import get_db_session
from app.models.user import User

logger = logging.getLogger(__name__)

# Sibling router without HTTP Bearer deps (mirrors admin security WS pattern).
router = APIRouter(tags=["3d"], include_in_schema=False)


async def _authenticate_user_websocket(
    websocket: WebSocket,
    db_session: AsyncSession,
) -> User | None:
    """Validate JWT from ``?access_token=`` or ``Authorization`` header."""

    token = (websocket.query_params.get("access_token") or "").strip()
    if not token:
        auth_header = websocket.headers.get("authorization") or ""
        scheme, _, value = auth_header.partition(" ")
        if scheme.lower() == "bearer":
            token = value.strip()
    if not token:
        await websocket.close(code=4401)
        return None

    try:
        payload = decode_and_validate_token(token, expected_type="access")
    except InvalidTokenError:
        await websocket.close(code=4401)
        return None

    subject = payload.get("sub")
    if not isinstance(subject, str) or not subject.strip():
        await websocket.close(code=4401)
        return None
    try:
        user_id = UUID(subject)
    except ValueError:
        await websocket.close(code=4401)
        return None

    user = await db_session.scalar(select(User).where(User.id == user_id).limit(1))
    if user is None:
        await websocket.close(code=4401)
        return None
    return user


@router.websocket("/ws/v1/3d/tasks/{task_id}")
async def three_d_task_progress_websocket(
    websocket: WebSocket,
    task_id: UUID,
    db_session: AsyncSession = Depends(get_db_session),
) -> None:
    """Push JSON progress frames whenever Redis progress for ``task_id`` changes."""

    await websocket.accept()
    user = await _authenticate_user_websocket(websocket, db_session)
    if user is None:
        return

    settings = get_settings()
    service = build_three_d_service(db_session)
    try:
        task = await service.get_for_user(task_id=task_id, user_id=user.id)
    except Exception:
        await websocket.close(code=4404)
        return

    progress_cache = RedisThreeDProgressCache(
        ttl_seconds=settings.three_d_progress_ttl_seconds
    )
    interval = settings.three_d_ws_poll_interval_seconds
    last_payload: dict | None = None

    async def _send_snapshot(snapshot: ThreeDProgressSnapshot) -> bool:
        nonlocal last_payload
        payload = snapshot.to_dict()
        if payload == last_payload:
            return snapshot.status in TERMINAL_THREE_D_STATUSES
        last_payload = payload
        await websocket.send_json(payload)
        return snapshot.status in TERMINAL_THREE_D_STATUSES

    # Immediate snapshot (Redis → DB fallback).
    cached = await progress_cache.get(task_id)
    if cached is not None:
        if await _send_snapshot(cached):
            await websocket.close(code=1000)
            return
    else:
        if await _send_snapshot(ThreeDProgressSnapshot.from_task_view(task)):
            await websocket.close(code=1000)
            return

    stop = asyncio.Event()

    async def _pubsub_loop() -> None:
        try:
            async for payload in progress_cache.subscribe_payloads(task_id):
                if stop.is_set():
                    break
                try:
                    snapshot = ThreeDProgressSnapshot.from_dict(payload)
                except (KeyError, TypeError, ValueError):
                    continue
                if await _send_snapshot(snapshot):
                    stop.set()
                    break
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.debug("3D WS pubsub loop ended task_id=%s", task_id, exc_info=True)

    async def _poll_loop() -> None:
        """Fallback: re-read Redis (and DB) when pub/sub is quiet."""

        try:
            while not stop.is_set():
                await asyncio.sleep(interval)
                if stop.is_set():
                    break
                snapshot = await progress_cache.get(task_id)
                if snapshot is None:
                    refreshed = await service.get_for_user(
                        task_id=task_id, user_id=user.id
                    )
                    snapshot = ThreeDProgressSnapshot.from_task_view(refreshed)
                if await _send_snapshot(snapshot):
                    stop.set()
                    break
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.debug("3D WS poll loop ended task_id=%s", task_id, exc_info=True)

    pubsub_task = asyncio.create_task(_pubsub_loop(), name=f"3d-ws-pubsub-{task_id}")
    poll_task = asyncio.create_task(_poll_loop(), name=f"3d-ws-poll-{task_id}")
    try:
        while not stop.is_set():
            done, _pending = await asyncio.wait(
                {pubsub_task, poll_task},
                timeout=interval,
                return_when=asyncio.FIRST_COMPLETED,
            )
            if stop.is_set():
                break
            if pubsub_task.done() and poll_task.done():
                break
            # Keep the surviving loop running.
            if pubsub_task in done and not poll_task.done():
                continue
            if poll_task in done and not pubsub_task.done():
                continue
    except WebSocketDisconnect:
        logger.debug("3D progress WebSocket disconnected task_id=%s", task_id)
    except Exception:
        logger.exception("3D progress WebSocket failed task_id=%s", task_id)
        try:
            await websocket.close(code=1011)
        except Exception:
            return
    finally:
        stop.set()
        for task_handle in (pubsub_task, poll_task):
            task_handle.cancel()
            try:
                await task_handle
            except asyncio.CancelledError:
                pass
            except Exception:
                pass
        try:
            if websocket.client_state.name != "DISCONNECTED":
                await websocket.close(code=1000)
        except Exception:
            pass


@router.websocket("/ws/v1/3d/video/{video_task_id}")
async def three_d_video_progress_websocket(
    websocket: WebSocket,
    video_task_id: UUID,
    db_session: AsyncSession = Depends(get_db_session),
) -> None:
    """Push frame/encode progress for a 360° video render job."""

    await websocket.accept()
    user = await _authenticate_user_websocket(websocket, db_session)
    if user is None:
        return

    settings = get_settings()
    service = build_three_d_video_render_service(db_session)
    try:
        task = await service.get_for_user(
            video_task_id=video_task_id, user_id=user.id
        )
    except Exception:
        await websocket.close(code=4404)
        return

    progress_cache = RedisThreeDVideoProgressCache(
        ttl_seconds=settings.three_d_progress_ttl_seconds
    )
    interval = settings.three_d_ws_poll_interval_seconds
    last_payload: dict | None = None

    async def _send_snapshot(snapshot: ThreeDVideoProgressSnapshot) -> bool:
        nonlocal last_payload
        payload = snapshot.to_dict()
        if payload == last_payload:
            return snapshot.status in TERMINAL_THREE_D_VIDEO_STATUSES
        last_payload = payload
        await websocket.send_json(payload)
        return snapshot.status in TERMINAL_THREE_D_VIDEO_STATUSES

    cached = await progress_cache.get(video_task_id)
    if cached is not None:
        if await _send_snapshot(cached):
            await websocket.close(code=1000)
            return
    else:
        if await _send_snapshot(ThreeDVideoProgressSnapshot.from_task_view(task)):
            await websocket.close(code=1000)
            return

    stop = asyncio.Event()

    async def _pubsub_loop() -> None:
        try:
            async for payload in progress_cache.subscribe_payloads(video_task_id):
                if stop.is_set():
                    break
                try:
                    snapshot = ThreeDVideoProgressSnapshot.from_dict(payload)
                except (KeyError, TypeError, ValueError):
                    continue
                if await _send_snapshot(snapshot):
                    stop.set()
                    break
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.debug(
                "3D video WS pubsub loop ended video_task_id=%s",
                video_task_id,
                exc_info=True,
            )

    async def _poll_loop() -> None:
        try:
            while not stop.is_set():
                await asyncio.sleep(interval)
                if stop.is_set():
                    break
                snapshot = await progress_cache.get(video_task_id)
                if snapshot is None:
                    refreshed = await service.get_for_user(
                        video_task_id=video_task_id,
                        user_id=user.id,
                    )
                    snapshot = ThreeDVideoProgressSnapshot.from_task_view(refreshed)
                if await _send_snapshot(snapshot):
                    stop.set()
                    break
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.debug(
                "3D video WS poll loop ended video_task_id=%s",
                video_task_id,
                exc_info=True,
            )

    pubsub_task = asyncio.create_task(
        _pubsub_loop(), name=f"3d-video-ws-pubsub-{video_task_id}"
    )
    poll_task = asyncio.create_task(
        _poll_loop(), name=f"3d-video-ws-poll-{video_task_id}"
    )
    try:
        while not stop.is_set():
            done, _pending = await asyncio.wait(
                {pubsub_task, poll_task},
                timeout=interval,
                return_when=asyncio.FIRST_COMPLETED,
            )
            if stop.is_set():
                break
            if pubsub_task.done() and poll_task.done():
                break
            if pubsub_task in done and not poll_task.done():
                continue
            if poll_task in done and not pubsub_task.done():
                continue
    except WebSocketDisconnect:
        logger.debug(
            "3D video progress WebSocket disconnected video_task_id=%s",
            video_task_id,
        )
    except Exception:
        logger.exception(
            "3D video progress WebSocket failed video_task_id=%s", video_task_id
        )
        try:
            await websocket.close(code=1011)
        except Exception:
            return
    finally:
        stop.set()
        for task_handle in (pubsub_task, poll_task):
            task_handle.cancel()
            try:
                await task_handle
            except asyncio.CancelledError:
                pass
            except Exception:
                pass
        try:
            if websocket.client_state.name != "DISCONNECTED":
                await websocket.close(code=1000)
        except Exception:
            pass
