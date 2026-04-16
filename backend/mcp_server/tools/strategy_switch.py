"""MCP tool for AI auto-strategy switching — wraps /api/bot/strategy-apply with guards."""

import httpx
import redis.asyncio as redis_lib
from loguru import logger

from mcp_server.strategy_switch_guard import StrategySwitchGuard
from mcp_server.tools import backend_url as _backend_url

_guard: StrategySwitchGuard | None = None


def init_strategy_switch(redis_client: redis_lib.Redis) -> None:
    """Initialize the strategy switch guard with Redis."""
    global _guard
    _guard = StrategySwitchGuard(redis_client)


def _require_guard() -> StrategySwitchGuard:
    if _guard is None:
        raise RuntimeError("Strategy switch guard not initialized — call init_strategy_switch() first")
    return _guard


async def apply_strategy(
    symbol: str,
    strategy_name: str,
    params: str | None = None,
    reasoning: str = "",
) -> dict:
    """Apply a strategy to the trading engine based on market regime analysis.

    Only works when enable_auto_strategy_switch is ON.
    Subject to cooldown (1h) and daily limits (3/day).
    Respects rollout mode: shadow/paper = log only.

    Args:
        symbol: Trading symbol (e.g. "GOLD", "BTCUSD")
        strategy_name: Strategy to switch to (e.g. "ema_crossover", "breakout")
        params: Optional JSON string of strategy parameters
        reasoning: Why the switch is needed (evidence from regime detection)

    Returns:
        Dict with applied (bool), strategy, symbol, and reason if rejected.
    """
    guard = _require_guard()

    # Validate switch against guards
    result = await guard.validate_switch(symbol, strategy_name)
    if not result.allowed:
        logger.info(f"Strategy switch blocked [{symbol}] → {strategy_name}: {result.reason}")
        return {
            "applied": False,
            "strategy": strategy_name,
            "symbol": symbol,
            "reason": result.reason,
        }

    # Parse params if provided as JSON string
    import json

    parsed_params = None
    if params:
        try:
            parsed_params = json.loads(params)
        except json.JSONDecodeError as e:
            logger.warning(f"apply_strategy: invalid params JSON for {symbol}: {e}")
            parsed_params = None

    # Call backend API to apply strategy
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.put(
                f"{_backend_url()}/api/bot/strategy-apply",
                json={
                    "name": strategy_name,
                    "params": parsed_params,
                    "symbol": symbol,
                    "reasoning": reasoning[:500],
                },
            )
            if resp.status_code != 200:
                return {
                    "applied": False,
                    "strategy": strategy_name,
                    "symbol": symbol,
                    "reason": f"Backend returned {resp.status_code}: {resp.text[:200]}",
                }
    except Exception as e:
        return {
            "applied": False,
            "strategy": strategy_name,
            "symbol": symbol,
            "reason": f"Failed to call backend: {e}",
        }

    # Record successful switch
    await guard.record_switch(symbol, strategy_name, reasoning)

    logger.info(f"Strategy switched [{symbol}] → {strategy_name} | {reasoning[:100]}")
    return {
        "applied": True,
        "strategy": strategy_name,
        "symbol": symbol,
        "reasoning": reasoning[:200],
    }


async def get_switch_status(symbol: str = "GOLD") -> dict:
    """Get current auto-strategy-switch status for a symbol.

    Args:
        symbol: Trading symbol

    Returns:
        Dict with enabled, current_strategy, cooldown info, daily count.
    """
    guard = _require_guard()
    return await guard.get_status(symbol)
