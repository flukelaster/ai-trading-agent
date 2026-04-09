"""
Bot control API routes.
"""

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import BotEvent
from app.db.session import get_db

router = APIRouter(prefix="/api/bot", tags=["bot"])

# Bot engine will be injected via app.state
_bot = None


def set_bot(bot):
    global _bot
    _bot = bot


def get_bot():
    if _bot is None:
        raise HTTPException(status_code=503, detail="Bot not initialized")
    return _bot


class StrategyUpdate(BaseModel):
    name: str
    params: dict | None = None


class SettingsUpdate(BaseModel):
    use_ai_filter: bool | None = None
    ai_confidence_threshold: float | None = None
    paper_trade: bool | None = None
    timeframe: str | None = None
    max_risk_per_trade: float | None = None
    max_daily_loss: float | None = None
    max_concurrent_trades: int | None = None
    max_lot: float | None = None


@router.post("/start")
async def start_bot():
    bot = get_bot()
    await bot.start()
    return {"status": "started"}


@router.post("/stop")
async def stop_bot():
    bot = get_bot()
    await bot.stop()
    return {"status": "stopped"}


@router.post("/emergency-stop")
async def emergency_stop():
    bot = get_bot()
    result = await bot.emergency_stop()
    return {"status": "emergency_stopped", "result": result}


@router.get("/status")
async def get_status():
    bot = get_bot()
    status = bot.get_status()
    # Add sentiment if available
    if bot.sentiment_analyzer:
        sentiment = await bot.sentiment_analyzer.get_latest_sentiment()
        status["sentiment"] = sentiment.to_dict()
    return status


@router.get("/account")
async def get_account():
    bot = get_bot()
    if bot.paper_trade:
        unrealized = sum(p.get("profit", 0) for p in bot._paper_positions)
        return {
            "balance": bot._paper_balance,
            "equity": bot._paper_balance + unrealized,
            "margin": 0,
            "free_margin": bot._paper_balance + unrealized,
            "profit": unrealized,
        }
    result = await bot.connector.get_account()
    if not result.get("success"):
        return {"balance": 0, "equity": 0, "margin": 0, "free_margin": 0, "profit": 0, "currency": "USD", "error": result.get("error")}
    return result["data"]


@router.put("/strategy")
async def update_strategy(data: StrategyUpdate):
    bot = get_bot()
    try:
        await bot.update_strategy(data.name, data.params)
        return {"status": "updated", "strategy": data.name}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.put("/settings")
async def update_settings(data: SettingsUpdate):
    bot = get_bot()
    await bot.update_settings(
        use_ai_filter=data.use_ai_filter,
        ai_confidence_threshold=data.ai_confidence_threshold,
        paper_trade=data.paper_trade,
        timeframe=data.timeframe,
        max_risk_per_trade=data.max_risk_per_trade,
        max_daily_loss=data.max_daily_loss,
        max_concurrent_trades=data.max_concurrent_trades,
        max_lot=data.max_lot,
    )
    return {"status": "updated"}


@router.get("/events")
async def get_events(
    days: int = Query(1, ge=1, le=30),
    event_type: str | None = None,
    limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
):
    """Get bot events — signals, blocks, trades, errors."""
    cutoff = datetime.utcnow() - timedelta(days=days)
    query = select(BotEvent).where(BotEvent.created_at >= cutoff)
    if event_type:
        query = query.where(BotEvent.event_type == event_type)
    query = query.order_by(desc(BotEvent.created_at)).limit(limit)

    result = await db.execute(query)
    events = result.scalars().all()

    return {
        "events": [
            {
                "id": e.id,
                "type": e.event_type.value,
                "message": e.message,
                "created_at": e.created_at.isoformat(),
            }
            for e in events
        ],
        "total": len(events),
    }
