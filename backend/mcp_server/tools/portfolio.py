"""MCP tools for portfolio overview — account info, exposure, correlation."""

from app.mt5.connector import MT5BridgeConnector
from app.risk.correlation import check_correlation_conflict

_connector: MT5BridgeConnector | None = None


def _get_connector() -> MT5BridgeConnector:
    global _connector
    if _connector is None:
        _connector = MT5BridgeConnector()
    return _connector


async def get_account() -> dict:
    """Get account summary — balance, equity, margin, profit.

    Returns:
        Dict with account information.
    """
    result = await _get_connector().get_account()
    if not result.get("success"):
        return {"error": result.get("error", "Failed to get account")}
    return result["data"]


async def get_exposure() -> dict:
    """Get portfolio exposure breakdown by symbol.

    Returns:
        Dict with per-symbol position counts, total lots, and unrealized P&L.
    """
    result = await _get_connector().get_positions()
    if not result.get("success"):
        return {"error": result.get("error", "Failed to get positions")}

    positions = result.get("data", [])
    exposure: dict[str, dict] = {}

    for p in positions:
        sym = p.get("symbol", "unknown")
        if sym not in exposure:
            exposure[sym] = {"count": 0, "total_lot": 0.0, "unrealized_pnl": 0.0, "direction": []}
        exposure[sym]["count"] += 1
        exposure[sym]["total_lot"] += p.get("lot", 0)
        exposure[sym]["unrealized_pnl"] += p.get("profit", 0)
        order_type = p.get("type", "")
        if order_type not in exposure[sym]["direction"]:
            exposure[sym]["direction"].append(order_type)

    return {
        "total_positions": len(positions),
        "symbols": exposure,
    }


def check_correlation(symbol: str, signal: int, active_positions: dict[str, list[dict]]) -> dict:
    """Check for correlation conflicts before opening a new position.

    Args:
        symbol: Symbol to trade
        signal: Direction (1=BUY, -1=SELL)
        active_positions: Dict of symbol -> list of position dicts

    Returns:
        Dict with has_conflict (bool) and reason.
    """
    has_conflict, reason = check_correlation_conflict(symbol, signal, active_positions)
    return {"has_conflict": has_conflict, "reason": reason}
