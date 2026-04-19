"""
WebSocket endpoint — pushes real-time updates to connected clients.
"""

import json

import redis.asyncio as redis
from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect
from loguru import logger

router = APIRouter()

CHANNELS = [
    "price_update",
    "position_update",
    "bot_event",
    "sentiment_update",
    "status_update",
]


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket, token: str | None = Query(None)):
    # Validate auth if enabled
    from app.auth import _auth_enabled, verify_token

    if _auth_enabled():
        if not token or not verify_token(token):
            await websocket.close(code=4001, reason="Authentication required")
            return

    await websocket.accept()
    logger.info("WebSocket client connected")

    redis_client = None
    pubsub = None
    try:
        from app.config import settings

        redis_client = redis.from_url(settings.redis_url)
        pubsub = redis_client.pubsub()
        await pubsub.subscribe(*CHANNELS)

        while True:
            message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
            if message and message["type"] == "message":
                data = {
                    "channel": message["channel"].decode()
                    if isinstance(message["channel"], bytes)
                    else message["channel"],
                    "data": json.loads(message["data"])
                    if isinstance(message["data"], str | bytes)
                    else message["data"],
                }
                await websocket.send_json(data)

    except WebSocketDisconnect:
        logger.info("WebSocket client disconnected")
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
    finally:
        if pubsub:
            await pubsub.unsubscribe(*CHANNELS)
            await pubsub.close()
        if redis_client:
            await redis_client.close()
