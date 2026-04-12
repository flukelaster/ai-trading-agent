"""
WebSocket endpoint for live runner log streaming.

Subscribes to Redis pub/sub channel `runner:{runner_id}:logs`.
"""

import asyncio

import redis.asyncio as redis_lib
from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect
from loguru import logger

router = APIRouter()


@router.websocket("/ws/runners/{runner_id}/logs")
async def runner_logs_stream(
    websocket: WebSocket,
    runner_id: int,
    token: str | None = Query(None),
):
    """Stream runner logs in real-time via WebSocket."""
    # Validate auth if enabled
    from app.auth import _auth_enabled, verify_token
    if _auth_enabled():
        if not token or not verify_token(token):
            await websocket.close(code=4001, reason="Authentication required")
            return

    await websocket.accept()
    logger.info(f"Runner logs WebSocket connected: runner_id={runner_id}")

    redis_client = None
    pubsub = None
    try:
        from app.config import settings
        redis_client = redis_lib.from_url(settings.redis_url)
        pubsub = redis_client.pubsub()
        channel = f"runner:{runner_id}:logs"
        await pubsub.subscribe(channel)

        while True:
            message = await pubsub.get_message(
                ignore_subscribe_messages=True, timeout=1.0
            )
            if message and message["type"] == "message":
                data = message["data"]
                if isinstance(data, bytes):
                    data = data.decode("utf-8")
                await websocket.send_text(data)

    except WebSocketDisconnect:
        logger.info(f"Runner logs WebSocket disconnected: runner_id={runner_id}")
    except Exception as e:
        logger.error(f"Runner logs WebSocket error: {e}")
    finally:
        if pubsub:
            await pubsub.unsubscribe()
            await pubsub.close()
        if redis_client:
            await redis_client.close()
