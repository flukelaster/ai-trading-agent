"""
Webhook endpoints — receive external trading signals.

TradingView: POST /api/webhooks/tradingview
"""

import os

from fastapi import APIRouter, HTTPException, Request
from loguru import logger
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/webhooks", tags=["webhooks"])

_manager = None


def init_webhooks(manager):
    global _manager
    _manager = manager


class TradingViewAlert(BaseModel):
    symbol: str = Field(min_length=2, max_length=32, pattern=r"^[A-Za-z0-9._-]+$")
    action: str = Field(pattern=r"^(?i:BUY|SELL)$")
    price: float | None = None
    key: str = Field(min_length=8, max_length=256)
    timestamp: int | None = Field(None, description="Unix seconds — reject if older than WEBHOOK_MAX_AGE_SECONDS")
    nonce: str | None = Field(
        None,
        max_length=64,
        pattern=r"^[A-Za-z0-9_-]+$",
        description="Unique per-alert token — rejected on replay",
    )


WEBHOOK_MAX_AGE_SECONDS = 60
_WEBHOOK_NONCE_TTL_SECONDS = 300


@router.post("/tradingview")
async def tradingview_webhook(alert: TradingViewAlert, request: Request):
    """
    Receive TradingView alert and execute trade via strategy engine.

    Each alert MUST include:
      key       — shared secret (HMAC-compared)
      timestamp — unix seconds, rejected if older than WEBHOOK_MAX_AGE_SECONDS
      nonce     — unique token, rejected on replay within _WEBHOOK_NONCE_TTL_SECONDS
    """
    # Validate webhook key. Fall back to the encrypted Secret row if no env var
    # is set so operators can rotate the key via the UI without redeploying.
    expected_key = os.environ.get("TRADINGVIEW_WEBHOOK_KEY", "")
    if not expected_key:
        try:
            from app.db.session import async_session, get_secret_or_none
            from app.vault import vault as vault_singleton

            async with async_session() as db:
                secret = await get_secret_or_none(db, "tradingview_webhook_key")
                if secret and secret.encrypted_value and secret.nonce:
                    expected_key = vault_singleton.decrypt(secret.encrypted_value, secret.nonce) or ""
        except Exception as e:
            logger.warning(f"webhook secret lookup failed: {type(e).__name__}")

    if not expected_key:
        raise HTTPException(status_code=503, detail="TradingView webhook key not configured")

    import hmac

    if not hmac.compare_digest(alert.key, expected_key):
        logger.warning(f"TradingView webhook: invalid key from {request.client.host if request.client else 'unknown'}")
        raise HTTPException(status_code=401, detail="Invalid webhook key")

    # Timestamp + nonce check to block replay attacks.
    if alert.timestamp is None or alert.nonce is None:
        raise HTTPException(status_code=400, detail="timestamp and nonce required")

    import time

    now = int(time.time())
    if abs(now - alert.timestamp) > WEBHOOK_MAX_AGE_SECONDS:
        raise HTTPException(status_code=401, detail="webhook expired")

    redis_client = getattr(request.app.state, "redis", None)
    if redis_client is not None:
        nonce_key = f"webhook:nonce:{alert.nonce}"
        # SETNX + EXPIRE: returns True only if the nonce has not been seen.
        if not await redis_client.set(nonce_key, "1", nx=True, ex=_WEBHOOK_NONCE_TTL_SECONDS):
            raise HTTPException(status_code=409, detail="replay detected")

    if _manager is None:
        raise HTTPException(status_code=503, detail="Bot manager not initialized")

    # Normalize
    symbol = alert.symbol.upper()
    action = alert.action.upper()
    if action not in ("BUY", "SELL"):
        raise HTTPException(status_code=400, detail=f"Invalid action: {action}. Must be BUY or SELL")

    # Get engine for symbol (resolves aliases, e.g., GOLD → GOLDmicro)
    from app.api.routes.bot import _get_engine

    try:
        engine = _get_engine(symbol)
    except HTTPException as e:
        available = list(_manager.engines.keys())
        raise HTTPException(status_code=400, detail=f"Symbol {symbol} not active. Available: {available}") from e

    signal = 1 if action == "BUY" else -1

    # Execute through risk manager (regime, confidence, drawdown all apply)
    try:
        # Get account balance
        account = await engine.connector.get_account()
        if not account.get("success"):
            return {"executed": False, "reason": "Cannot get account info"}
        balance = account["data"]["balance"]

        # Get market data for ATR/SL/TP calculation
        df = await engine.market_data.get_ohlcv(engine.symbol, engine.timeframe, 200)
        if df.empty:
            return {"executed": False, "reason": "No market data available"}

        # Check event filter
        from app.constants import EVENT_BLOCK_HOURS

        near_event = engine._event_calendar.is_near_event(hours_before=EVENT_BLOCK_HOURS)

        # Place order through engine (applies all risk checks)
        await engine._size_and_place_order(
            signal=signal,
            signal_label=action,
            df=df,
            balance=balance,
            ai_sentiment=None,
            near_event=near_event,
        )

        logger.info(f"TradingView webhook executed: {action} {symbol}")

        # Telegram notification
        if engine.notifier:
            import asyncio

            asyncio.create_task(
                engine.notifier.send_message(f"<b>TradingView Webhook</b>\n{action} {symbol} (external signal)")
            )

        return {
            "executed": True,
            "symbol": symbol,
            "action": action,
            "message": f"{action} {symbol} signal processed",
        }

    except Exception as e:
        logger.error(f"TradingView webhook error: {e}")
        return {"executed": False, "reason": "Internal execution error"}
