"""
Bot control API routes (multi-symbol).
"""

from datetime import datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app.cache import cached
from loguru import logger
from pydantic import BaseModel, Field
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import log_audit
from app.auth import require_auth
from app.config import settings
from app.db.models import BotEvent
from app.db.session import get_db

router = APIRouter(
    prefix="/api/bot",
    tags=["bot"],
    dependencies=[Depends(require_auth)],
)

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
    """Get a specific engine or the first one as default.

    Resolves symbol aliases (e.g., GOLD → GOLDmicro if that's what's configured).
    """
    mgr = get_manager()
    if symbol:
        engine = mgr.get_engine(symbol)
        if not engine:
            # Try reverse alias: frontend sends "GOLD" but engine is "GOLDmicro"
            from app.config import SYMBOL_ALIASES
            for alias, canonical in SYMBOL_ALIASES.items():
                if canonical == symbol and alias in mgr.engines:
                    return mgr.engines[alias]
            raise HTTPException(status_code=404, detail=f"Symbol {symbol} not configured")
        return engine
    # Default: first engine (backward compat)
    return next(iter(mgr.engines.values()))


class StrategyUpdate(BaseModel):
    name: str
    params: dict | None = None
    symbol: str | None = None


class StrategyApply(BaseModel):
    name: str
    params: dict | None = None
    symbol: str | None = None
    reasoning: str = ""


class SettingsUpdate(BaseModel):
    symbol: str | None = None
    use_ai_filter: bool | None = None
    ai_confidence_threshold: float | None = Field(None, ge=0.0, le=1.0)
    paper_trade: bool | None = None
    timeframe: str | None = None
    max_risk_per_trade: float | None = Field(None, ge=0.001, le=0.10)
    max_daily_loss: float | None = Field(None, ge=0.01, le=0.20)
    max_concurrent_trades: int | None = Field(None, ge=1, le=20)
    max_lot: float | None = Field(None, ge=0.01, le=1.0)
    fixed_lot: float | None = Field(None, ge=0.01, le=1.0)
    lot_mode: Literal["fixed", "auto"] | None = None
    enable_auto_strategy_switch: bool | None = None


@router.post("/start", dependencies=[Depends(require_auth)])
async def start_bot(request: Request, symbol: str | None = Query(None), db: AsyncSession = Depends(get_db)):
    mgr = get_manager()
    await mgr.start(symbol)
    await log_audit(
        db, "bot_start", resource=f"symbol:{symbol or 'all'}",
        ip=request.client.host if request.client else None,
    )
    return {"status": "started", "symbol": symbol or "all"}


@router.post("/stop", dependencies=[Depends(require_auth)])
async def stop_bot(request: Request, symbol: str | None = Query(None), db: AsyncSession = Depends(get_db)):
    mgr = get_manager()
    await mgr.stop(symbol)
    await log_audit(
        db, "bot_stop", resource=f"symbol:{symbol or 'all'}",
        ip=request.client.host if request.client else None,
    )
    return {"status": "stopped", "symbol": symbol or "all"}


@router.post("/emergency-stop", dependencies=[Depends(require_auth)])
async def emergency_stop(request: Request, symbol: str | None = Query(None), db: AsyncSession = Depends(get_db)):
    mgr = get_manager()
    result = await mgr.emergency_stop(symbol)
    await log_audit(
        db, "bot_emergency_stop", resource=f"symbol:{symbol or 'all'}",
        detail={"result": result},
        ip=request.client.host if request.client else None,
    )
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
            "accounts": [],
        }

    # Collect balances from each unique connector
    seen_connectors: set[int] = set()
    accounts: list[dict] = []

    for symbol, engine in mgr.engines.items():
        conn_id = id(engine.connector)
        if conn_id in seen_connectors:
            continue
        seen_connectors.add(conn_id)

        result = await engine.connector.get_account()
        if result.get("success"):
            data = result["data"]
            # Detect connector type
            is_binance = hasattr(engine.connector, '_sign')  # BinanceConnector has _sign method
            accounts.append({
                "connector": "binance" if is_binance else "mt5",
                "balance": data.get("balance", 0),
                "equity": data.get("equity", 0),
                "margin": data.get("margin", 0),
                "free_margin": data.get("free_margin", 0),
                "profit": data.get("profit", 0),
                "currency": data.get("currency", "USD"),
            })

    # Primary balance = first account (MT5) for backward compat
    primary = accounts[0] if accounts else {"balance": 0, "equity": 0, "margin": 0, "free_margin": 0, "profit": 0}

    # Peak balance + drawdown from peak
    peak_balance = 0.0
    drawdown_pct = 0.0
    try:
        from app.risk.circuit_breaker import CircuitBreaker
        balance = primary.get("balance", 0)
        peak_balance = await CircuitBreaker.update_peak_balance(first_engine.redis, balance)
        if peak_balance > 0:
            drawdown_pct = (peak_balance - balance) / peak_balance
    except Exception:
        pass

    return {
        **primary,
        "accounts": accounts,
        "peak_balance": round(peak_balance, 2),
        "drawdown_pct": round(drawdown_pct, 4),
    }


@router.put("/strategy", dependencies=[Depends(require_auth)])
async def update_strategy(data: StrategyUpdate, request: Request, db: AsyncSession = Depends(get_db)):
    engine = _get_engine(data.symbol)
    ip = request.client.host if request.client else None
    if data.name == "ai_autonomous":
        try:
            await engine.redis.set("trading_mode", "ai_autonomous")
        except Exception as e:
            logger.debug(f"Redis trading_mode write failed: {e}")
        settings.trading_mode = "ai_autonomous"
        engine.strategy = None
        await log_audit(db, "bot_strategy_change", resource=f"symbol:{engine.symbol}",
                        detail={"strategy": "ai_autonomous"}, ip=ip)
        return {"status": "updated", "strategy": "ai_autonomous", "symbol": engine.symbol}
    try:
        await engine.redis.set("trading_mode", "strategy")
    except Exception as e:
        logger.debug(f"Redis trading_mode write failed: {e}")
    settings.trading_mode = "strategy"
    try:
        await engine.update_strategy(data.name, data.params)
        await log_audit(db, "bot_strategy_change", resource=f"symbol:{engine.symbol}",
                        detail={"strategy": data.name, "params": data.params}, ip=ip)
        return {"status": "updated", "strategy": data.name, "symbol": engine.symbol}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.put("/strategy-apply", dependencies=[Depends(require_auth)])
async def apply_strategy_in_ai_mode(data: StrategyApply):
    """Apply a strategy to the engine without changing trading mode.

    Used by AI auto-strategy-switch to set a real strategy while staying in ai_autonomous mode.
    """
    engine = _get_engine(data.symbol)
    try:
        await engine.update_strategy(data.name, data.params)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    from app.db.models import BotEventType

    try:
        await engine._log_event(
            BotEventType.STRATEGY_CHANGED,
            f"[Auto-Switch] → {data.name} | {data.reasoning[:200]}",
        )
    except Exception as e:
        logger.debug(f"Failed to log strategy switch event: {e}")

    return {"status": "applied", "strategy": data.name, "symbol": engine.symbol}


@router.put("/settings", dependencies=[Depends(require_auth)])
async def update_settings(data: SettingsUpdate, request: Request, db: AsyncSession = Depends(get_db)):
    from app.bot.engine import _UNSET
    resolved_fixed_lot = _UNSET
    if data.lot_mode == "auto":
        resolved_fixed_lot = None
    elif data.lot_mode == "fixed" and data.fixed_lot is not None:
        resolved_fixed_lot = data.fixed_lot

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
            fixed_lot=resolved_fixed_lot,
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
                fixed_lot=resolved_fixed_lot,
            )

    # Persist auto-strategy-switch flag to Redis (global, not per-engine)
    if data.enable_auto_strategy_switch is not None:
        try:
            engine = _get_engine()
            await engine.redis.set(
                "enable_auto_strategy_switch",
                "1" if data.enable_auto_strategy_switch else "0",
            )
            settings.enable_auto_strategy_switch = data.enable_auto_strategy_switch
        except Exception as e:
            logger.debug(f"Redis enable_auto_strategy_switch write failed: {e}")

    await log_audit(
        db, "bot_settings_change", resource=f"symbol:{data.symbol or 'all'}",
        detail=data.model_dump(exclude_none=True),
        ip=request.client.host if request.client else None,
    )
    return {"status": "updated"}


@router.post("/reset-peak", dependencies=[Depends(require_auth)])
async def reset_peak_balance():
    """Reset peak balance to current balance (fixes drawdown after account switch)."""
    engine = _get_engine()
    account = await engine.connector.get_account()
    if not account.get("success"):
        raise HTTPException(status_code=503, detail="Cannot get account info")
    balance = account["data"]["balance"]
    await engine.redis.set("circuit:peak_balance", str(balance))
    return {"peak_balance": balance, "message": f"Peak reset to ${balance:.2f}"}


@router.get("/events")
async def get_events(
    request: Request,
    days: int = Query(1, ge=1, le=30),
    event_type: str | None = None,
    limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
):
    """Get bot events — signals, blocks, trades, errors."""

    async def _fetch():
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

    redis_client = getattr(request.app.state, "redis", None)
    if redis_client is None:
        return await _fetch()
    return await cached(
        redis_client,
        f"cache:bot_events:{days}:{event_type or ''}:{limit}",
        10,
        _fetch,
    )
