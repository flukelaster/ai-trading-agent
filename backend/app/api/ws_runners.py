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

    redis_client = None
    pubsub = None
    websocket_accepted = False

    try:
        if _auth_enabled():
            if not token or not verify_token(token):
                return  # Reject connection, no websocket.accept() called

        from app.config import settings
        redis_client = redis_lib.from_url(settings.redis_url)
        pubsub = redis_client.pubsub()
        channel = f"runner:{runner_id}:logs"
        await pubsub.subscribe(channel)

        await websocket.accept()
        websocket_accepted = True
        logger.info(f"Runner logs WebSocket connected: runner_id={runner_id}")

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
        # Ensure websocket is closed on errors
        if websocket_accepted:
            try:
                await websocket.close()
            except Exception:
                pass
        # Always cleanup Redis resources
        if pubsub:
            try:
                await pubsub.unsubscribe()
                await pubsub.close()
            except Exception:
                pass
        if redis_client:
            try:
                await redis_client.close()
            except Exception:
                pass
