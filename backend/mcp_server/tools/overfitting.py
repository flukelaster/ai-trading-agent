"""MCP tool for composite overfitting score — wraps /api/backtest/overfitting-score."""

import httpx

from mcp_server.tools import backend_url as _backend_url


async def compute_overfitting_score(
    strategy: str,
    symbol: str,
    timeframe: str = "M15",
    source: str = "db",
    count: int = 5000,
) -> dict:
    """Compute a composite overfitting score (0-100%) for a strategy.

    Runs walk-forward analysis, permutation test, and monte carlo simulation,
    then combines results into a single overfitting percentage with grade.

    Args:
        strategy: Strategy name (e.g. "ema_crossover", "breakout", "mean_reversion")
        symbol: Trading symbol (e.g. "GOLD", "BTCUSD", "USDJPY")
        timeframe: Candle timeframe (default "M15")
        source: Data source — "db" (historical) or "mt5" (live)
        count: Number of candles to use for analysis

    Returns:
        Dict with overfitting_pct (0-100), grade (healthy/moderate/overfit),
        component breakdown, and individual test summaries.
    """
    try:
        async with httpx.AsyncClient(timeout=300) as client:
            resp = await client.post(
                f"{_backend_url()}/api/backtest/overfitting-score",
                json={
                    "strategy": strategy,
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "source": source,
                    "count": count,
                },
            )
            if resp.status_code == 200:
                return resp.json()
            return {"error": f"Backend returned {resp.status_code}: {resp.text}"}
    except httpx.TimeoutException:
        return {"error": "Overfitting score computation timed out (>300s)"}
    except Exception as e:
        return {"error": f"Failed to compute overfitting score: {e}"}
