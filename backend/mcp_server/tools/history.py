"""MCP tools for trade history — queries backend API."""

import httpx

from mcp_server.tools import auth_headers, backend_url as _backend_url


async def get_trade_history(days: int = 7, symbol: str | None = None, limit: int = 50) -> dict:
    """Get recent trade history.

    Args:
        days: Number of days to look back
        symbol: Optional symbol filter
        limit: Max number of trades to return

    Returns:
        Dict with list of historical trades.
    """
    try:
        params: dict = {"days": days, "limit": limit}
        if symbol:
            params["symbol"] = symbol
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(f"{_backend_url()}/api/history/trades", params=params, headers=auth_headers())
            if resp.status_code == 200:
                return {"trades": resp.json()}
            return {"error": f"Backend returned {resp.status_code}"}
    except Exception as e:
        return {"error": f"Failed to fetch trade history: {e}"}


async def get_daily_pnl(symbol: str | None = None) -> dict:
    """Get daily P&L summary.

    Args:
        symbol: Optional symbol filter

    Returns:
        Dict with daily P&L data.
    """
    try:
        params: dict = {}
        if symbol:
            params["symbol"] = symbol
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(f"{_backend_url()}/api/history/daily-pnl", params=params, headers=auth_headers())
            if resp.status_code == 200:
                return {"daily_pnl": resp.json()}
            return {"error": f"Backend returned {resp.status_code}"}
    except Exception as e:
        return {"error": f"Failed to fetch daily PnL: {e}"}


async def get_performance(days: int = 30, symbol: str | None = None) -> dict:
    """Get performance statistics.

    Args:
        days: Number of days to analyze
        symbol: Optional symbol filter

    Returns:
        Dict with performance metrics (win rate, Sharpe, max drawdown, etc.).
    """
    try:
        params: dict = {"days": days}
        if symbol:
            params["symbol"] = symbol
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(f"{_backend_url()}/api/history/performance", params=params, headers=auth_headers())
            if resp.status_code == 200:
                return resp.json()
            return {"error": f"Backend returned {resp.status_code}"}
    except Exception as e:
        return {"error": f"Failed to fetch performance: {e}"}
