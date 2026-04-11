"""
Bot control API routes (multi-symbol).
"""

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import BotEvent
from app.db.session import get_db

router = APIRouter(prefix="/api/bot", tags=["bot"])

# BotManager will be injected via app.state
_manager = None


def set_manager(manager):
    global _manager
    _manager = manager


def get_manager():
    if _manager is None:
        raise HTTPException(status_code=503, detail="Bot not initialized")
    return _manager


def _get_engine(symbol: str | None = None):
    """Get a specific engine or the first one as default."""
    mgr = get_manager()
    if symbol:
        engine = mgr.get_engine(symbol)
        if not engine:
            raise HTTPException(status_code=404, detail=f"Symbol {symbol} not configured")
        return engine
    # Default: first engine (backward compat)
    return next(iter(mgr.engines.values()))


class StrategyUpdate(BaseModel):
    name: str
    params: dict | None = None
    symbol: str | None = None


class SettingsUpdate(BaseModel):
    symbol: str | None = None
    use_ai_filter: bool | None = None
    ai_confidence_threshold: float | None = None
    paper_trade: bool | None = None
    timeframe: str | None = None
    max_risk_per_trade: float | None = None
    max_daily_loss: float | None = None
    max_concurrent_trades: int | None = None
    max_lot: float | None = None


@router.post("/start")
async def start_bot(symbol: str | None = Query(None)):
    mgr = get_manager()
    await mgr.start(symbol)
    return {"status": "started", "symbol": symbol or "all"}


@router.post("/stop")
async def stop_bot(symbol: str | None = Query(None)):
    mgr = get_manager()
    await mgr.stop(symbol)
    return {"status": "stopped", "symbol": symbol or "all"}


@router.post("/emergency-stop")
async def emergency_stop(symbol: str | None = Query(None)):
    mgr = get_manager()
    result = await mgr.emergency_stop(symbol)
    return {"status": "emergency_stopped", "result": result}


@router.get("/status")
async def get_status(symbol: str | None = Query(None)):
    mgr = get_manager()
    if symbol:
        engine = _get_engine(symbol)
        status = engine.get_status()
        if engine.sentiment_analyzer:
            sentiment = await engine.sentiment_analyzer.get_latest_sentiment()
            status["sentiment"] = sentiment.to_dict()
        return status
    # Aggregate status
    return mgr.get_status()


@router.get("/account")
async def get_account():
    mgr = get_manager()
    # Account is shared across all symbols (same MT5 account)
    first_engine = next(iter(mgr.engines.values()))
    if first_engine.paper_trade:
        unrealized = sum(
            p.get("profit", 0)
            for engine in mgr.engines.values()
            for p in engine._paper_positions
        )
        balance = first_engine._paper_balance
        return {
            "balance": balance,
            "equity": balance + unrealized,
            "margin": 0,
            "free_margin": balance + unrealized,
            "profit": unrealized,
        }
    result = await first_engine.connector.get_account()
    if not result.get("success"):
        return {"balance": 0, "equity": 0, "margin": 0, "free_margin": 0, "profit": 0, "currency": "USD", "error": result.get("error")}
    return result["data"]


@router.put("/strategy")
async def update_strategy(data: StrategyUpdate):
    engine = _get_engine(data.symbol)
    try:
        await engine.update_strategy(data.name, data.params)
        return {"status": "updated", "strategy": data.name, "symbol": engine.symbol}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.put("/settings")
async def update_settings(data: SettingsUpdate):
    if data.symbol:
        engine = _get_engine(data.symbol)
        await engine.update_settings(
            use_ai_filter=data.use_ai_filter,
            ai_confidence_threshold=data.ai_confidence_threshold,
            paper_trade=data.paper_trade,
            timeframe=data.timeframe,
            max_risk_per_trade=data.max_risk_per_trade,
            max_daily_loss=data.max_daily_loss,
            max_concurrent_trades=data.max_concurrent_trades,
            max_lot=data.max_lot,
        )
    else:
        mgr = get_manager()
        for engine in mgr.engines.values():
            await engine.update_settings(
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
