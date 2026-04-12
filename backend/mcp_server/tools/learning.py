"""
MCP tools for self-reflection & learning loop.

Analyzes past trades to extract patterns, identify mistakes, and suggest improvements.
Used by the Reflector agent before each trading session.
"""

import httpx

from mcp_server.tools import backend_url as _backend_url


async def analyze_recent_trades(days: int = 7, symbol: str | None = None) -> dict:
    """Analyze recent trade outcomes to identify patterns and mistakes.

    Fetches trade history and computes learning-relevant statistics:
    win/loss streaks, best/worst trades, strategy performance, time-of-day patterns.

    Args:
        days: Number of days to look back
        symbol: Optional symbol filter

    Returns:
        Dict with trade analysis, patterns, and suggested learnings.
    """
    try:
        params: dict = {"days": days, "limit": 100}
        if symbol:
            params["symbol"] = symbol

        async with httpx.AsyncClient(timeout=15) as client:
            trades_resp = await client.get(f"{_backend_url()}/api/history/trades", params=params)
            perf_resp = await client.get(
                f"{_backend_url()}/api/history/performance",
                params={"days": days, "symbol": symbol} if symbol else {"days": days},
            )

        trades = trades_resp.json() if trades_resp.status_code == 200 else []
        performance = perf_resp.json() if perf_resp.status_code == 200 else {}

        if not trades:
            return {"analysis": "No trades found in the period", "trade_count": 0}

        # Compute patterns
        wins = [t for t in trades if t.get("profit", 0) > 0]
        losses = [t for t in trades if t.get("profit", 0) < 0]

        # Best and worst trades
        sorted_by_profit = sorted(trades, key=lambda t: t.get("profit", 0))
        worst = sorted_by_profit[:3] if len(sorted_by_profit) >= 3 else sorted_by_profit
        best = sorted_by_profit[-3:] if len(sorted_by_profit) >= 3 else sorted_by_profit

        # Strategy breakdown
        strategy_stats: dict[str, dict] = {}
        for t in trades:
            strat = t.get("strategy_name", "unknown")
            if strat not in strategy_stats:
                strategy_stats[strat] = {"count": 0, "wins": 0, "total_pnl": 0.0}
            strategy_stats[strat]["count"] += 1
            if t.get("profit", 0) > 0:
                strategy_stats[strat]["wins"] += 1
            strategy_stats[strat]["total_pnl"] += t.get("profit", 0)

        for strat, stats in strategy_stats.items():
            stats["win_rate"] = round(stats["wins"] / stats["count"], 2) if stats["count"] > 0 else 0

        # Average win/loss size
        avg_win = sum(t.get("profit", 0) for t in wins) / len(wins) if wins else 0
        avg_loss = sum(t.get("profit", 0) for t in losses) / len(losses) if losses else 0

        return {
            "trade_count": len(trades),
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": round(len(wins) / len(trades), 2) if trades else 0,
            "avg_win": round(avg_win, 2),
            "avg_loss": round(avg_loss, 2),
            "risk_reward_ratio": round(abs(avg_win / avg_loss), 2) if avg_loss != 0 else 0,
            "best_trades": [{"profit": t.get("profit"), "symbol": t.get("symbol"), "strategy": t.get("strategy_name")} for t in best],
            "worst_trades": [{"profit": t.get("profit"), "symbol": t.get("symbol"), "strategy": t.get("strategy_name")} for t in worst],
            "strategy_performance": strategy_stats,
            "overall_performance": performance,
        }
    except Exception as e:
        return {"error": f"Failed to analyze trades: {e}"}


async def get_optimization_history(limit: int = 5) -> dict:
    """Get recent AI optimization attempts and their outcomes.

    Args:
        limit: Number of optimization records to fetch

    Returns:
        Dict with optimization history entries.
    """
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(f"{_backend_url()}/api/ai/optimization/latest")
            if resp.status_code == 200:
                return {"optimizations": resp.json()}
            return {"optimizations": [], "note": "No optimization history available"}
    except Exception as e:
        return {"error": f"Failed to fetch optimization history: {e}"}


async def detect_regime(symbol: str = "GOLD", timeframe: str = "M15") -> dict:
    """Detect the current market regime (trending/ranging/volatile).

    Uses ATR and ADX from the full analysis to classify the regime.

    Args:
        symbol: Trading symbol
        timeframe: Candle timeframe

    Returns:
        Dict with regime classification and supporting data.
    """
    from mcp_server.tools.indicators import full_analysis

    analysis = await full_analysis(symbol, timeframe, count=200)
    if "error" in analysis:
        return analysis

    adx = analysis.get("adx", 0)
    atr = analysis.get("atr", 0)
    trend = analysis.get("trend", "neutral")
    trend_strength = analysis.get("trend_strength", "weak")
    rsi = analysis.get("rsi", 50)
    bb_position = analysis.get("price_vs_bb", "inside")

    # Classify regime
    if adx > 25 and trend_strength == "strong":
        regime = "trending"
        regime_detail = f"Strong {trend} trend (ADX={adx:.0f})"
    elif adx < 20 and bb_position == "inside":
        regime = "ranging"
        regime_detail = f"Low directional movement (ADX={adx:.0f}), price inside bands"
    elif atr > 0 and bb_position in ("above_upper", "below_lower"):
        regime = "volatile"
        regime_detail = f"Price at Bollinger extremes, ATR elevated"
    else:
        regime = "transitional"
        regime_detail = f"Mixed signals (ADX={adx:.0f}, trend={trend})"

    # Strategy recommendations by regime
    recommended_strategies: dict[str, list[str]] = {
        "trending": ["ema_crossover", "breakout"],
        "ranging": ["mean_reversion", "rsi_filter"],
        "volatile": ["breakout"],
        "transitional": ["ensemble"],
    }

    return {
        "symbol": symbol,
        "regime": regime,
        "regime_detail": regime_detail,
        "recommended_strategies": recommended_strategies.get(regime, ["ensemble"]),
        "adx": round(adx, 1),
        "atr": round(atr, 5),
        "trend": trend,
        "rsi": round(rsi, 1),
    }
