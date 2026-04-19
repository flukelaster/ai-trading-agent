"""MCP tools for broker operations — GUARDRAIL-GATED.

Every order execution MUST pass through TradingGuardrails.validate_order()
before reaching the MT5 Bridge. The agent cannot bypass this.
"""

import redis.asyncio as redis_lib
from loguru import logger
from app.mt5.connector import MT5BridgeConnector
from app.notifications.telegram import TelegramNotifier
from app.risk.circuit_breaker import CircuitBreaker
from mcp_server.guardrails import TradingGuardrails

_connector: MT5BridgeConnector | None = None
_guardrails: TradingGuardrails | None = None
_notifier: TelegramNotifier | None = None
_redis: redis_lib.Redis | None = None


def init_broker(redis: redis_lib.Redis) -> None:
    """Initialize broker with Redis for guardrails. Called once at agent startup."""
    global _connector, _guardrails, _notifier, _redis
    _connector = MT5BridgeConnector()
    _guardrails = TradingGuardrails(redis)
    _notifier = TelegramNotifier()
    _redis = redis


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

    # Resolve symbol to broker name (e.g. GOLD → GOLDmicro)
    # AI sends canonical names but MT5 may use different names (GOLDmicro on XM)
    # Use the live engine list — engines are keyed by actual broker symbols from SYMBOLS env var
    try:
        from app.api.routes.bot import get_manager
        mgr = get_manager()
        if symbol not in mgr.engines:
            # AI sent canonical name (GOLD), find matching broker name in engines
            from app.config import SYMBOL_ALIASES
            for broker_name, canonical in SYMBOL_ALIASES.items():
                if canonical == symbol and broker_name in mgr.engines:
                    logger.info(f"Symbol resolved: {symbol} → {broker_name}")
                    symbol = broker_name
                    break
            else:
                logger.warning(f"Symbol '{symbol}' not found in engines: {list(mgr.engines.keys())}")
    except Exception as e:
        logger.warning(f"Symbol resolution failed for '{symbol}': {e}")

    # Get current state for guardrail checks (concurrent)
    import asyncio as _aio
    account_res, positions_res, tick_res = await _aio.gather(
        _connector.get_account(),
        _connector.get_positions(),
        _connector.get_tick(symbol),
    )

    if not all(r.get("success") for r in [account_res, positions_res, tick_res]):
        failed = []
        if not account_res.get("success"):
            failed.append(f"account: {account_res.get('error', 'unknown')}")
        if not positions_res.get("success"):
            failed.append(f"positions: {positions_res.get('error', 'unknown')}")
        if not tick_res.get("success"):
            failed.append(f"tick: {tick_res.get('error', 'unknown')}")
        logger.error(f"place_order pre-check failed: {', '.join(failed)}")
        return {"error": f"Failed to fetch data for guardrail validation: {', '.join(failed)}"}

    account = account_res["data"]
    positions = positions_res.get("data", [])
    tick = tick_res["data"]

    spread = tick.get("ask", 0) - tick.get("bid", 0)
    avg_spread = spread  # Simplified — production would track rolling average

    # ─── GUARDRAIL CHECK (non-bypassable) ────────────────────────────────
    # daily_pnl must come from CircuitBreaker (closed-trade realized P&L).
    # account.profit is *floating* unrealized P&L, which would let open winners
    # mask realized losses and bypass the daily-loss limit.
    cb = CircuitBreaker(_redis, symbol=symbol)
    realized_daily_pnl = await cb.get_daily_pnl()

    result = await _guardrails.validate_order(
        symbol=symbol,
        lot=lot,
        order_type=order_type,
        current_positions=positions,
        account_balance=account.get("balance", 0),
        daily_pnl=realized_daily_pnl,
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
    logger.info(f"place_order [{symbol}] {order_type} lot={lot} sl={sl} tp={tp} mode={rollout_mode}")
    order_result = await _connector.place_order(
        symbol=symbol,
        order_type=order_type,
        lot=lot,
        sl=sl,
        tp=tp,
        comment=f"[Agent:{rollout_mode}] {comment}",
    )
    logger.info(f"place_order result [{symbol}]: {order_result}")

    if order_result.get("success"):
        await _guardrails.record_trade(is_win=True)  # Updated on close
        data = order_result["data"]
        # Send Telegram notification
        if _notifier:
            try:
                await _notifier.send_trade_alert(
                    trade_type=order_type, symbol=symbol,
                    price=data.get("price", 0), sl=sl, tp=tp, lot=lot,
                )
            except Exception as e:
                logger.error(f"Telegram notify failed: {e}")
        # Log AI-initiated trade to event DB
        try:
            from app.bot.manager import get_manager
            from app.db.models import BotEventType
            engine = get_manager().engines.get(symbol)
            if engine:
                await engine._log_event(
                    BotEventType.TRADE_OPENED,
                    f"[AI Agent] {order_type} {lot} {symbol} @ {data.get('price', 0):.2f} SL={sl} TP={tp} [{rollout_mode}]",
                )
        except Exception as e:
            logger.warning(f"Event log failed: {e}")
        return {
            "executed": True,
            "mode": rollout_mode,
            "order": data,
        }
    else:
        return {
            "executed": False,
            "error": order_result.get("error", "Order execution failed"),
        }


async def modify_position(ticket: int, sl: float | None = None, tp: float | None = None) -> dict:
    """Modify stop-loss and/or take-profit of an existing position.

    Guardrails:
    - Non-live rollout modes intercept and log instead of mutating broker state.
    - Stop-loss cannot be widened to more than MAX_SL_WIDEN_MULT × the distance
      from the current entry price; the AI agent can't neutralize risk by
      dragging SL to zero.
    """
    _require_init()
    rollout_mode = _guardrails.get_rollout_mode()
    if rollout_mode in ("shadow", "paper"):
        logger.info(f"[{rollout_mode}] modify_position intercepted: ticket={ticket} sl={sl} tp={tp}")
        return {"modified": False, "rollout": rollout_mode, "ticket": ticket}

    if sl is not None:
        positions_res = await _connector.get_positions()
        if positions_res.get("success"):
            for p in positions_res.get("data", []):
                if p.get("ticket") != ticket:
                    continue
                current_sl = p.get("sl") or 0
                entry = p.get("open_price") or p.get("price") or 0
                if current_sl and entry:
                    current_dist = abs(entry - current_sl)
                    new_dist = abs(entry - sl)
                    MAX_SL_WIDEN_MULT = 2.0
                    if new_dist > current_dist * MAX_SL_WIDEN_MULT:
                        return {
                            "modified": False,
                            "rejected": True,
                            "reason": (
                                f"SL widen {new_dist:.5f} exceeds {MAX_SL_WIDEN_MULT}x "
                                f"current distance {current_dist:.5f}"
                            ),
                        }
                break

    result = await _connector.modify_position(ticket, sl=sl, tp=tp)
    if result.get("success"):
        return {"modified": True, "ticket": ticket}
    return {"modified": False, "error": result.get("error", "Modification failed")}


async def close_position(ticket: int) -> dict:
    """Close a specific position by ticket number.

    In shadow/paper rollout modes the close is intercepted (logged only) so the
    AI agent cannot liquidate a real account while we're still dry-running.
    """
    _require_init()
    rollout_mode = _guardrails.get_rollout_mode()

    # Get position info before closing for notification
    positions_res = await _connector.get_positions()
    pos_info = None
    if positions_res.get("success"):
        for p in positions_res.get("data", []):
            if p.get("ticket") == ticket:
                pos_info = p
                break

    if rollout_mode in ("shadow", "paper"):
        logger.info(f"[{rollout_mode}] close_position intercepted: ticket={ticket}")
        return {"closed": False, "rollout": rollout_mode, "ticket": ticket}

    result = await _connector.close_position(ticket)
    if result.get("success"):
        # Send Telegram notification
        if _notifier and pos_info:
            try:
                await _notifier.send_trade_alert(
                    trade_type=f"CLOSE_{pos_info.get('type', '')}",
                    symbol=pos_info.get("symbol", ""),
                    price=pos_info.get("price_current", 0),
                    sl=0, tp=0, lot=pos_info.get("volume", 0),
                    extra=f"${pos_info.get('profit', 0):+.2f}",
                )
            except Exception as e:
                logger.error(f"Telegram notify failed: {e}")
        # Log AI-initiated close to event DB
        if pos_info:
            try:
                from app.bot.manager import get_manager
                from app.db.models import BotEventType
                sym = pos_info.get("symbol", "")
                engine = get_manager().engines.get(sym)
                if engine:
                    await engine._log_event(
                        BotEventType.TRADE_CLOSED,
                        f"[AI Agent] CLOSE {sym} ticket={ticket} P&L=${pos_info.get('profit', 0):+.2f}",
                    )
            except Exception as e:
                logger.warning(f"Event log failed: {e}")
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
