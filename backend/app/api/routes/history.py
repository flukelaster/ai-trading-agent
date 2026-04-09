"""
Trade history API routes.
"""

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Trade
from app.db.session import get_db

router = APIRouter(prefix="/api/history", tags=["history"])


@router.get("/trades")
async def get_trades(
    days: int = Query(30, ge=1, le=365),
    strategy: str | None = None,
    trade_type: str | None = None,
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    cutoff = datetime.utcnow() - timedelta(days=days)
    query = select(Trade).where(Trade.open_time >= cutoff)

    if strategy:
        query = query.where(Trade.strategy_name == strategy)
    if trade_type:
        query = query.where(Trade.type == trade_type.upper())

    query = query.order_by(desc(Trade.open_time)).offset(offset).limit(limit)
    result = await db.execute(query)
    trades = result.scalars().all()

    return {
        "trades": [
            {
                "id": t.id,
                "ticket": t.ticket,
                "symbol": t.symbol,
                "type": t.type,
                "lot": t.lot,
                "open_price": t.open_price,
                "close_price": t.close_price,
                "sl": t.sl,
                "tp": t.tp,
                "open_time": t.open_time.isoformat(),
                "close_time": t.close_time.isoformat() if t.close_time else None,
                "profit": t.profit,
                "strategy_name": t.strategy_name,
                "ai_sentiment_label": t.ai_sentiment_label,
                "ai_sentiment_score": t.ai_sentiment_score,
            }
            for t in trades
        ],
        "total": len(trades),
    }


@router.get("/daily-pnl")
async def get_daily_pnl(db: AsyncSession = Depends(get_db)):
    """Today's closed trade P&L (UTC day boundary)."""
    today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    result = await db.execute(
        select(Trade).where(
            Trade.close_time >= today,
            Trade.profit.isnot(None),
        )
    )
    trades = result.scalars().all()

    total = round(sum(t.profit for t in trades), 2)
    wins = sum(1 for t in trades if t.profit > 0)
    losses = sum(1 for t in trades if t.profit <= 0)

    return {
        "daily_pnl": total,
        "trade_count": len(trades),
        "wins": wins,
        "losses": losses,
    }


@router.get("/performance")
async def get_performance(
    days: int = Query(30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
):
    cutoff = datetime.utcnow() - timedelta(days=days)
    result = await db.execute(
        select(Trade).where(Trade.open_time >= cutoff, Trade.profit.isnot(None))
    )
    trades = result.scalars().all()

    if not trades:
        return {"total_trades": 0, "win_rate": 0, "total_profit": 0, "monthly_pnl": []}

    wins = [t for t in trades if t.profit > 0]
    total_profit = sum(t.profit for t in trades)

    return {
        "total_trades": len(trades),
        "win_rate": round(len(wins) / len(trades), 4) if trades else 0,
        "total_profit": round(total_profit, 2),
        "avg_profit": round(total_profit / len(trades), 2),
    }
