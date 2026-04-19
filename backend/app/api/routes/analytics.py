"""
Analytics API routes — advanced performance metrics.
"""

import math
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import require_auth
from app.cache import cached
from app.db.models import Trade
from app.db.session import get_db

router = APIRouter(
    prefix="/api/analytics",
    tags=["analytics"],
    dependencies=[Depends(require_auth)],
)


@router.get("/performance")
async def get_performance_analytics(
    request: Request,
    symbol: str | None = None,
    days: int = Query(30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
):
    from types import SimpleNamespace

    from app.api.routes.bot import _manager

    if symbol:
        from app.config import resolve_broker_symbol

        symbol = resolve_broker_symbol(symbol)

    async def _compute():
        return await _compute_performance(symbol, days, db, _manager, SimpleNamespace)

    redis_client = getattr(request.app.state, "redis", None)
    if redis_client is None:
        return await _compute()
    return await cached(
        redis_client,
        f"cache:analytics_perf:{symbol or 'all'}:{days}",
        60,
        _compute,
    )


async def _compute_performance(symbol, days, db, _manager, SimpleNamespace):

    cutoff = datetime.utcnow() - timedelta(days=days)
    query = select(Trade).where(
        Trade.open_time >= cutoff,
        Trade.profit.isnot(None),
        Trade.close_time.isnot(None),
        Trade.is_archived.is_(False),
    )
    if symbol:
        query = query.where(Trade.symbol == symbol)
    query = query.order_by(Trade.close_time)

    result = await db.execute(query)
    db_trades = list(result.scalars().all())
    db_tickets = {t.ticket for t in db_trades}
    trades: list = list(db_trades)

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
                    trades.append(
                        SimpleNamespace(
                            profit=deal_profit,
                            open_time=deal_time,
                            close_time=deal_time,
                            expected_price=None,
                            open_price=deal.get("open_price") or deal.get("price"),
                            symbol=deal.get("symbol", ""),
                        )
                    )
        except Exception:
            pass

    trades.sort(key=lambda t: t.close_time)

    if not trades:
        return {
            "total_trades": 0,
            "win_rate": 0,
            "profit_factor": 0,
            "sharpe_ratio": 0,
            "sortino_ratio": 0,
            "calmar_ratio": 0,
            "max_drawdown": 0,
            "max_drawdown_pct": 0,
            "recovery_factor": 0,
            "avg_win": 0,
            "avg_loss": 0,
            "largest_win": 0,
            "largest_loss": 0,
            "avg_trade_duration_min": 0,
            "consecutive_wins": 0,
            "consecutive_losses": 0,
            "best_hour": None,
            "worst_hour": None,
            "best_day": None,
            "worst_day": None,
            "equity_curve": [],
            "daily_returns": [],
        }

    profits = [t.profit for t in trades]
    wins = [p for p in profits if p > 0]
    losses = [p for p in profits if p <= 0]

    total_profit = sum(profits)
    gross_profit = sum(wins) if wins else 0
    gross_loss = abs(sum(losses)) if losses else 0
    win_rate = len(wins) / len(profits) if profits else 0
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")

    # Equity curve + max drawdown
    equity = []
    running = 0
    peak = 0
    max_dd = 0
    max_dd_pct = 0
    for t in trades:
        running += t.profit
        equity.append({"time": t.close_time.isoformat(), "equity": round(running, 2)})
        if running > peak:
            peak = running
        dd = peak - running
        if dd > max_dd:
            max_dd = dd
        if peak > 0:
            dd_pct = dd / peak
            if dd_pct > max_dd_pct:
                max_dd_pct = dd_pct

    # Sharpe Ratio (annualized, assuming daily returns)
    if len(profits) >= 2:
        mean_return = sum(profits) / len(profits)
        std_return = math.sqrt(sum((p - mean_return) ** 2 for p in profits) / (len(profits) - 1))
        sharpe = (mean_return / std_return * math.sqrt(252)) if std_return > 0 else 0
    else:
        sharpe = 0

    # Sortino Ratio (only downside deviation)
    downside = [p for p in profits if p < 0]
    if downside and len(profits) >= 2:
        mean_return = sum(profits) / len(profits)
        downside_dev = math.sqrt(sum(p**2 for p in downside) / len(downside))
        sortino = (mean_return / downside_dev * math.sqrt(252)) if downside_dev > 0 else 0
    else:
        sortino = 0

    # Calmar Ratio
    calmar = total_profit / max_dd if max_dd > 0 else 0

    # Recovery Factor
    recovery = total_profit / max_dd if max_dd > 0 else 0

    # Consecutive wins/losses
    max_consec_wins = 0
    max_consec_losses = 0
    cur_wins = 0
    cur_losses = 0
    for p in profits:
        if p > 0:
            cur_wins += 1
            cur_losses = 0
            max_consec_wins = max(max_consec_wins, cur_wins)
        else:
            cur_losses += 1
            cur_wins = 0
            max_consec_losses = max(max_consec_losses, cur_losses)

    # Trade duration
    durations = []
    for t in trades:
        if t.close_time and t.open_time:
            dur = (t.close_time - t.open_time).total_seconds() / 60
            durations.append(dur)
    avg_duration = sum(durations) / len(durations) if durations else 0

    # Best/worst hour and day
    hour_pnl: dict[int, float] = {}
    day_pnl: dict[int, float] = {}
    for t in trades:
        h = t.open_time.hour
        d = t.open_time.weekday()
        hour_pnl[h] = hour_pnl.get(h, 0) + t.profit
        day_pnl[d] = day_pnl.get(d, 0) + t.profit

    best_hour = max(hour_pnl, key=hour_pnl.get) if hour_pnl else None
    worst_hour = min(hour_pnl, key=hour_pnl.get) if hour_pnl else None
    day_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    best_day = day_names[max(day_pnl, key=day_pnl.get)] if day_pnl else None
    worst_day = day_names[min(day_pnl, key=day_pnl.get)] if day_pnl else None

    # Daily returns for chart
    daily: dict[str, float] = {}
    for t in trades:
        day_key = t.close_time.strftime("%Y-%m-%d")
        daily[day_key] = daily.get(day_key, 0) + t.profit
    daily_returns = [{"date": k, "pnl": round(v, 2)} for k, v in sorted(daily.items())]

    # Slippage analysis
    slippage_values = []
    for t in trades:
        if t.expected_price and t.open_price:
            slip = abs(t.open_price - t.expected_price)
            slippage_values.append(slip)

    avg_slippage = sum(slippage_values) / len(slippage_values) if slippage_values else 0
    max_slippage = max(slippage_values) if slippage_values else 0

    return {
        "total_trades": len(trades),
        "win_rate": round(win_rate, 4),
        "profit_factor": round(profit_factor, 2),
        "total_profit": round(total_profit, 2),
        "sharpe_ratio": round(sharpe, 2),
        "sortino_ratio": round(sortino, 2),
        "calmar_ratio": round(calmar, 2),
        "max_drawdown": round(max_dd, 2),
        "max_drawdown_pct": round(max_dd_pct * 100, 1),
        "recovery_factor": round(recovery, 2),
        "avg_win": round(sum(wins) / len(wins), 2) if wins else 0,
        "avg_loss": round(sum(losses) / len(losses), 2) if losses else 0,
        "largest_win": round(max(profits), 2) if profits else 0,
        "largest_loss": round(min(profits), 2) if profits else 0,
        "avg_trade_duration_min": round(avg_duration, 1),
        "consecutive_wins": max_consec_wins,
        "consecutive_losses": max_consec_losses,
        "best_hour": best_hour,
        "worst_hour": worst_hour,
        "best_day": best_day,
        "worst_day": worst_day,
        "equity_curve": equity,
        "daily_returns": daily_returns,
        "avg_slippage": round(avg_slippage, 4),
        "max_slippage": round(max_slippage, 4),
        "slippage_trades": len(slippage_values),
    }


@router.get("/slippage")
async def get_slippage_analysis(
    symbol: str | None = None,
    days: int = Query(30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
):
    """Detailed slippage analysis: by hour, by strategy, total cost."""
    if symbol:
        from app.config import resolve_broker_symbol

        symbol = resolve_broker_symbol(symbol)

    cutoff = datetime.utcnow() - timedelta(days=days)
    query = select(Trade).where(
        Trade.open_time >= cutoff,
        Trade.expected_price.isnot(None),
        Trade.open_price.isnot(None),
        Trade.is_archived.is_(False),
    )
    if symbol:
        query = query.where(Trade.symbol == symbol)

    result = await db.execute(query)
    trades = result.scalars().all()

    if not trades:
        return {"total_trades": 0, "slippage_data": []}

    slippage_data = []
    by_hour: dict[int, list[float]] = {}
    by_strategy: dict[str, list[float]] = {}
    total_cost = 0.0

    for t in trades:
        if t.expected_price and t.open_price:
            if t.type == "BUY":
                slip = t.open_price - t.expected_price
            else:
                slip = t.expected_price - t.open_price

            slippage_data.append(slip)

            # By hour
            hour = t.open_time.hour if t.open_time else 0
            by_hour.setdefault(hour, []).append(slip)

            # By strategy
            strategy = t.strategy_name or "unknown"
            by_strategy.setdefault(strategy, []).append(slip)

            # Cost estimate (slip * lot * contract_size)
            from app.config import SYMBOL_PROFILES

            contract_size = SYMBOL_PROFILES.get(t.symbol, {}).get("contract_size", 100)
            total_cost += abs(slip) * (t.lot or 0.1) * contract_size

    if not slippage_data:
        return {"total_trades": len(trades), "avg_slippage": 0}

    sorted_slips = sorted(slippage_data)
    n = len(sorted_slips)

    return {
        "total_trades": n,
        "avg_slippage": round(sum(slippage_data) / n, 4),
        "median_slippage": round(sorted_slips[n // 2], 4),
        "p95_slippage": round(sorted_slips[int(n * 0.95)] if n >= 20 else sorted_slips[-1], 4),
        "max_slippage": round(max(slippage_data), 4),
        "total_cost_usd": round(total_cost, 2),
        "by_hour": {h: {"avg": round(sum(v) / len(v), 4), "count": len(v)} for h, v in sorted(by_hour.items())},
        "by_strategy": {s: {"avg": round(sum(v) / len(v), 4), "count": len(v)} for s, v in by_strategy.items()},
    }
