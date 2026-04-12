"""MCP tools for market data — wraps MT5BridgeConnector."""

from app.mt5.connector import MT5BridgeConnector

_connector: MT5BridgeConnector | None = None


def _get_connector() -> MT5BridgeConnector:
    global _connector
    if _connector is None:
        _connector = MT5BridgeConnector()
    return _connector


async def get_tick(symbol: str) -> dict:
    """Get current bid/ask tick for a symbol.

    Args:
        symbol: Trading symbol (e.g., "GOLD", "BTCUSD", "USDJPY")

    Returns:
        Dict with ask, bid prices and spread.
    """
    connector = _get_connector()
    result = await connector.get_tick(symbol)
    if not result.get("success"):
        return {"error": result.get("error", "Failed to get tick")}
    data = result["data"]
    spread = round(data.get("ask", 0) - data.get("bid", 0), 5)
    return {**data, "spread": spread}


async def get_ohlcv(symbol: str, timeframe: str = "M15", count: int = 100) -> dict:
    """Get OHLCV (candlestick) data for a symbol.

    Args:
        symbol: Trading symbol
        timeframe: Candle timeframe (M1, M5, M15, M30, H1, H4, D1)
        count: Number of candles to fetch (max 500)

    Returns:
        Dict with candle data list.
    """
    count = min(count, 500)
    connector = _get_connector()
    result = await connector.get_ohlcv(symbol, timeframe, count)
    if not result.get("success"):
        return {"error": result.get("error", "Failed to get OHLCV")}
    return {"symbol": symbol, "timeframe": timeframe, "count": len(result["data"]), "candles": result["data"]}


async def get_spread(symbol: str) -> dict:
    """Get current spread for a symbol in pips.

    Args:
        symbol: Trading symbol

    Returns:
        Dict with bid, ask, and spread values.
    """
    return await get_tick(symbol)
