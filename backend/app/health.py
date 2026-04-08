"""
Health check endpoint.
"""

from fastapi import APIRouter

router = APIRouter()


async def check_health(bot_engine, connector, redis_client, ai_client) -> dict:
    # MT5 Bridge
    mt5_ok = False
    try:
        result = await connector.get_health()
        mt5_ok = result.get("status") == "ok"
    except Exception:
        pass

    # Redis
    redis_ok = False
    try:
        await redis_client.ping()
        redis_ok = True
    except Exception:
        pass

    # AI
    ai_ok = ai_client.client is not None

    return {
        "status": "ok" if redis_ok else "degraded",
        "mt5_connected": mt5_ok,
        "redis_connected": redis_ok,
        "ai_available": ai_ok,
        "bot_state": bot_engine.state.value if bot_engine else "N/A",
    }
