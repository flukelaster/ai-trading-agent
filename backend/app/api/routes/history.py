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
    symbol: str | None = None,
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    from app.api.routes.bot import _manager
    from app.config import resolve_broker_symbol

    if symbol:
        symbol = resolve_broker_symbol(symbol)

    cutoff = datetime.utcnow() - timedelta(days=days)

    # 1. Pull from DB (with fallback if new columns not yet migrated)
    query = select(Trade).where(Trade.open_time >= cutoff, Trade.is_archived.is_(False))
    if strategy:
        query = query.where(Trade.strategy_name == strategy)
    if trade_type:
        query = query.where(Trade.type == trade_type.upper())
    if symbol:
        query = query.where(Trade.symbol == symbol)
    query = query.order_by(desc(Trade.open_time))

    try:
        result = await db.execute(query)
        db_trades = result.scalars().all()
    except Exception:
        # New columns not yet migrated — rollback and retry without ORM column mapping issue
        await db.rollback()
        from sqlalchemy import text
        raw = await db.execute(text(
            "SELECT id, ticket, symbol, type, lot, open_price, close_price, sl, tp, "
            "open_time, close_time, profit, strategy_name, ai_sentiment_score, ai_sentiment_label "
            f"FROM trades WHERE open_time >= :cutoff ORDER BY open_time DESC"
        ), {"cutoff": cutoff})
        db_trades = raw.fetchall()

    db_tickets = {getattr(t, "ticket", t[1] if isinstance(t, tuple) else 0) for t in db_trades}

    def _trade_dict(t) -> dict:
        if hasattr(t, "id"):
            return {
                "id": t.id, "ticket": t.ticket, "symbol": t.symbol, "type": t.type,
                "lot": t.lot, "open_price": t.open_price, "close_price": t.close_price,
                "sl": t.sl, "tp": t.tp,
                "open_time": t.open_time.isoformat(),
                "close_time": t.close_time.isoformat() if t.close_time else None,
                "profit": t.profit, "strategy_name": t.strategy_name,
                "ai_sentiment_label": getattr(t, "ai_sentiment_label", None),
                "ai_sentiment_score": getattr(t, "ai_sentiment_score", None),
                "trade_reason": getattr(t, "trade_reason", None),
                "pre_trade_snapshot": getattr(t, "pre_trade_snapshot", None),
                "post_trade_analysis": getattr(t, "post_trade_analysis", None),
                "source": "bot",
            }
        else:
            return {
                "id": t[0], "ticket": t[1], "symbol": t[2], "type": t[3],
                "lot": t[4], "open_price": t[5], "close_price": t[6],
                "sl": t[7], "tp": t[8],
                "open_time": t[9].isoformat() if t[9] else None,
                "close_time": t[10].isoformat() if t[10] else None,
                "profit": t[11], "strategy_name": t[12],
                "ai_sentiment_score": t[13], "ai_sentiment_label": t[14],
                "trade_reason": None, "pre_trade_snapshot": None, "post_trade_analysis": None,
                "source": "bot",
            }

    rows = [_trade_dict(t) for t in db_trades]

    # 2. Merge MT5 history (catches manual trades not in DB)
    if _manager is not None and not strategy:
        try:
            from app.api.routes.bot import _get_engine
            engine = _get_engine(symbol) if symbol else next(iter(_manager.engines.values()))
            mt5_result = await engine.connector.get_history(days=days, symbol=symbol or None)
            if mt5_result.get("success"):
                for deal in mt5_result.get("data", []):
                    ticket = deal.get("ticket")
                    if ticket in db_tickets:
                        continue
                    try:
                        deal_time = datetime.fromisoformat(deal["time"].replace("Z", ""))
                    except Exception:
                        deal_time = datetime.utcnow()
                    if deal_time < cutoff:
                        continue
                    deal_type = deal.get("type", "").upper()
                    if trade_type and deal_type != trade_type.upper():
                        continue
                    if symbol and deal.get("symbol") != symbol:
                        continue
                    rows.append({
                        "id": None,
                        "ticket": ticket,
                        "symbol": deal.get("symbol", ""),
                        "type": deal_type,
                        "lot": deal.get("lot", 0),
                        "open_price": deal.get("open_price") or deal.get("price", 0),
                        "close_price": deal.get("price", 0),
                        "sl": 0,
                        "tp": 0,
                        "open_time": deal_time.isoformat(),
                        "close_time": deal_time.isoformat(),
                        "profit": deal.get("profit", 0),
                        "strategy_name": "manual",
                        "ai_sentiment_label": None,
                        "ai_sentiment_score": None,
                        "source": "mt5",
                    })
        except Exception:
            pass

    # Sort by open_time desc, apply offset/limit
    rows.sort(key=lambda x: x["open_time"], reverse=True)
    paginated = rows[offset: offset + limit]

    return {"trades": paginated, "total": len(rows)}


@router.get("/daily-pnl")
async def get_daily_pnl(
    symbol: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    """Today's closed trade P&L — merges MT5 live history + DB records."""
    from app.api.routes.bot import _manager
    from app.config import resolve_broker_symbol

    if symbol:
        symbol = resolve_broker_symbol(symbol)

    today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)

    # 1. Try MT5 live history first (catches all trades — bot + manual)
    mt5_deals: list[dict] = []
    if _manager is not None:
        try:
            from app.api.routes.bot import _get_engine
            engine = _get_engine(symbol) if symbol else next(iter(_manager.engines.values()))
            result = await engine.connector.get_history(days=1, symbol=symbol or None)
            if result.get("success"):
                for deal in result.get("data", []):
                    try:
                        deal_time = datetime.fromisoformat(deal["time"].replace("Z", ""))
                    except Exception:
                        continue
                    if deal_time >= today and deal.get("profit") is not None:
                        if symbol and deal.get("symbol") != symbol:
                            continue
                        mt5_deals.append(deal)
        except Exception:
            pass

    # 2. Also pull from DB (covers paper trades and offline history)
    db_query = select(Trade).where(
        Trade.close_time >= today,
        Trade.profit.isnot(None),
        Trade.is_archived.is_(False),
    )
    if symbol:
        db_query = db_query.where(Trade.symbol == symbol)
    db_result = await db.execute(db_query)
    db_trades = db_result.scalars().all()

    # 3. Merge: prefer MT5 data; fallback to DB-only records not in MT5
    if mt5_deals:
        mt5_tickets = {d.get("ticket") for d in mt5_deals}
        extra_db = [t for t in db_trades if t.ticket not in mt5_tickets]
        profits = [d["profit"] for d in mt5_deals] + [t.profit for t in extra_db]
    else:
        profits = [t.profit for t in db_trades]

    total = round(sum(profits), 2)
    wins = sum(1 for p in profits if p > 0)
    losses = sum(1 for p in profits if p <= 0)

    return {
        "daily_pnl": total,
        "trade_count": len(profits),
        "wins": wins,
        "losses": losses,
        "source": "mt5" if mt5_deals else "db",
    }


@router.get("/performance")
async def get_performance(
    days: int = Query(30, ge=1, le=365),
    symbol: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    from app.api.routes.bot import _manager

    if symbol:
        from app.config import resolve_broker_symbol
        symbol = resolve_broker_symbol(symbol)

    cutoff = datetime.utcnow() - timedelta(days=days)
    query = select(Trade).where(Trade.open_time >= cutoff, Trade.profit.isnot(None), Trade.is_archived.is_(False))
    if symbol:
        query = query.where(Trade.symbol == symbol)
    result = await db.execute(query)
    db_trades = result.scalars().all()

    db_tickets = {t.ticket for t in db_trades}
    profits: list[float] = [t.profit for t in db_trades]

    # Merge MT5 history (catches manual trades not in DB)
    if _manager is not None:
        try:
            from app.api.routes.bot import _get_engine
            engine = _get_engine(symbol) if symbol else next(iter(_manager.engines.values()))
            mt5_result = await engine.connector.get_history(days=days, symbol=symbol or None)
            if mt5_result.get("success"):
                for deal in mt5_result.get("data", []):
                    ticket = deal.get("ticket")
                    if ticket in db_tickets:
                        continue
                    try:
                        deal_time = datetime.fromisoformat(deal["time"].replace("Z", ""))
                    except Exception:
                        continue
                    if deal_time < cutoff:
                        continue
                    if symbol and deal.get("symbol") != symbol:
                        continue
                    deal_profit = deal.get("profit")
                    if deal_profit is None:
                        continue
                    profits.append(deal_profit)
        except Exception:
            pass

    if not profits:
        return {"total_trades": 0, "win_rate": 0, "total_profit": 0, "avg_profit": 0}

    wins = [p for p in profits if p > 0]
    total_profit = sum(profits)

    return {
        "total_trades": len(profits),
        "win_rate": round(len(wins) / len(profits), 4),
        "total_profit": round(total_profit, 2),
        "avg_profit": round(total_profit / len(profits), 2),
    }
