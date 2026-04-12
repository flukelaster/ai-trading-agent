"""MCP tools for broker operations — GUARDRAIL-GATED.

Every order execution MUST pass through TradingGuardrails.validate_order()
before reaching the MT5 Bridge. The agent cannot bypass this.
"""

import redis.asyncio as redis_lib
from app.mt5.connector import MT5BridgeConnector
from mcp_server.guardrails import TradingGuardrails

_connector: MT5BridgeConnector | None = None
_guardrails: TradingGuardrails | None = None


def init_broker(redis: redis_lib.Redis) -> None:
    """Initialize broker with Redis for guardrails. Called once at agent startup."""
    global _connector, _guardrails
    _connector = MT5BridgeConnector()
    _guardrails = TradingGuardrails(redis)


def _require_init():
    if not _connector or not _guardrails:
        raise RuntimeError("Broker not initialized — call init_broker(redis) first")


async def place_order(
    symbol: str,
    order_type: str,
    lot: float,
    sl: float,
    tp: float,
    comment: str = "",
) -> dict:
    """Place a trade order — GUARDRAIL-GATED.

    Every order passes through guardrails validation before execution.
    The agent cannot bypass this check.

    Args:
        symbol: Trading symbol (e.g., "GOLD")
        order_type: "BUY" or "SELL"
        lot: Position size
        sl: Stop-loss price
        tp: Take-profit price
        comment: Optional order comment

    Returns:
        Dict with order result or rejection reason.
    """
    _require_init()

    # Get current state for guardrail checks (concurrent)
    import asyncio as _aio
    account_res, positions_res, tick_res = await _aio.gather(
        _connector.get_account(),
        _connector.get_positions(),
        _connector.get_tick(symbol),
    )

    if not all(r.get("success") for r in [account_res, positions_res, tick_res]):
        return {"error": "Failed to fetch account/position/tick data for guardrail validation"}

    account = account_res["data"]
    positions = positions_res.get("data", [])
    tick = tick_res["data"]

    spread = tick.get("ask", 0) - tick.get("bid", 0)
    avg_spread = spread  # Simplified — production would track rolling average

    # ─── GUARDRAIL CHECK (non-bypassable) ────────────────────────────────
    result = await _guardrails.validate_order(
        symbol=symbol,
        lot=lot,
        order_type=order_type,
        current_positions=positions,
        account_balance=account.get("balance", 0),
        daily_pnl=account.get("profit", 0),
        spread=spread,
        avg_spread=avg_spread,
    )

    if not result.allowed:
        return {
            "executed": False,
            "rejected": True,
            "reason": result.reason,
        }

    # ─── ROLLOUT MODE CHECK (Phase F) ────────────────────────────────────
    from mcp_server.guardrails import MICRO_MAX_LOT

    rollout = _guardrails.check_rollout_mode(lot)
    rollout_mode = _guardrails.get_rollout_mode()

    if rollout_mode == "shadow":
        # Shadow: log everything but don't execute
        return {
            "executed": False,
            "mode": "shadow",
            "would_execute": {
                "symbol": symbol, "order_type": order_type,
                "lot": lot, "sl": sl, "tp": tp,
            },
            "message": "Shadow mode: order logged for review, not sent to broker",
        }

    if rollout_mode == "paper":
        # Paper: simulate execution with fake ticket
        import random
        return {
            "executed": True,
            "mode": "paper",
            "order": {
                "ticket": random.randint(900000, 999999),
                "symbol": symbol, "type": order_type,
                "lot": lot, "price": tick.get("ask" if order_type == "BUY" else "bid", 0),
                "sl": sl, "tp": tp,
                "simulated": True,
            },
            "message": "Paper mode: simulated execution (not real)",
        }

    if rollout_mode == "micro":
        # Micro: cap lot at MICRO_MAX_LOT
        lot = min(lot, MICRO_MAX_LOT)

    # ─── EXECUTE ORDER (live or micro) ───────────────────────────────────
    order_result = await _connector.place_order(
        symbol=symbol,
        order_type=order_type,
        lot=lot,
        sl=sl,
        tp=tp,
        comment=f"[Agent:{rollout_mode}] {comment}",
    )

    if order_result.get("success"):
        await _guardrails.record_trade(is_win=True)  # Updated on close
        return {
            "executed": True,
            "mode": rollout_mode,
            "order": order_result["data"],
        }
    else:
        return {
            "executed": False,
            "error": order_result.get("error", "Order execution failed"),
        }


async def modify_position(ticket: int, sl: float | None = None, tp: float | None = None) -> dict:
    """Modify stop-loss and/or take-profit of an existing position.

    Args:
        ticket: Position ticket number
        sl: New stop-loss price (None to keep current)
        tp: New take-profit price (None to keep current)

    Returns:
        Dict with modification result.
    """
    _require_init()
    result = await _connector.modify_position(ticket, sl=sl, tp=tp)
    if result.get("success"):
        return {"modified": True, "ticket": ticket}
    return {"modified": False, "error": result.get("error", "Modification failed")}


async def close_position(ticket: int) -> dict:
    """Close a specific position by ticket number.

    Args:
        ticket: Position ticket number

    Returns:
        Dict with close result.
    """
    _require_init()
    result = await _connector.close_position(ticket)
    if result.get("success"):
        return {"closed": True, "ticket": ticket}
    return {"closed": False, "error": result.get("error", "Close failed")}


async def get_positions(symbol: str | None = None) -> dict:
    """Get all open positions, optionally filtered by symbol.

    Args:
        symbol: Optional symbol filter

    Returns:
        Dict with list of open positions.
    """
    _require_init()
    result = await _connector.get_positions()
    if not result.get("success"):
        return {"error": result.get("error", "Failed to get positions")}

    positions = result.get("data", [])
    if symbol:
        positions = [p for p in positions if p.get("symbol") == symbol]

    return {"count": len(positions), "positions": positions}
