"""
Order Executor — places and manages orders via MT5 Bridge with retry logic.
"""

import asyncio

from loguru import logger

from app.constants import MT5_MAGIC_NUMBER
from app.mt5.connector import MT5BridgeConnector

# Errors that should NOT be retried (permanent failures)
_NO_RETRY_ERRORS = {"margin", "insufficient", "invalid volume", "market closed", "symbol not found"}


def _resolve_broker(symbol: str) -> str:
    """Resolve canonical symbol → broker alias (e.g., GOLD → GOLDm#)."""
    try:
        from app.config import SYMBOL_PROFILES
        profile = SYMBOL_PROFILES.get(symbol)
        if profile:
            alias = profile.get("broker_alias")
            if alias:
                return alias
    except Exception:
        pass
    return symbol


class OrderExecutor:
    def __init__(self, connector: MT5BridgeConnector):
        self.connector = connector

    async def place_order(
        self, symbol: str, order_type: str, lot: float, sl: float, tp: float,
        comment: str = "", magic: int = MT5_MAGIC_NUMBER, max_retries: int = 3,
    ) -> dict:
        symbol = _resolve_broker(symbol)
        logger.info(f"Placing order: {order_type} {lot} {symbol} SL={sl} TP={tp}")

        for attempt in range(max_retries):
            result = await self.connector.place_order(symbol, order_type, lot, sl, tp, comment, magic)

            if result.get("success"):
                logger.info(f"Order placed: ticket={result['data'].get('ticket')} (attempt {attempt + 1})")
                result["attempt_count"] = attempt + 1
                return result

            error = str(result.get("error", "")).lower()

            # Don't retry permanent errors
            if any(e in error for e in _NO_RETRY_ERRORS):
                logger.error(f"Order failed (permanent): {result.get('error')}")
                result["attempt_count"] = attempt + 1
                return result

            # Retry transient errors with exponential backoff
            if attempt < max_retries - 1:
                wait = 2 ** attempt  # 1s, 2s, 4s
                logger.warning(f"Order failed (attempt {attempt + 1}/{max_retries}): {result.get('error')} — retrying in {wait}s")
                await asyncio.sleep(wait)
            else:
                logger.error(f"Order failed after {max_retries} attempts: {result.get('error')}")

        result["attempt_count"] = max_retries
        return result

    async def close_position(self, ticket: int) -> dict:
        logger.info(f"Closing position: {ticket}")
        result = await self.connector.close_position(ticket)
        if result.get("success"):
            logger.info(f"Position {ticket} closed")
        else:
            logger.error(f"Close position {ticket} failed: {result.get('error')}")
        return result

    async def close_all_positions(self, symbol: str | None = None) -> dict:
        if symbol:
            symbol = _resolve_broker(symbol)
        logger.warning(f"Closing ALL positions (symbol={symbol})")
        result = await self.connector.close_all_positions(symbol=symbol)
        return result

    async def get_open_positions(self, symbol: str | None = None) -> list[dict]:
        result = await self.connector.get_positions()
        if not result.get("success"):
            return []
        positions = result.get("data", [])
        if symbol:
            broker = _resolve_broker(symbol)
            positions = [p for p in positions if p.get("symbol") in (symbol, broker)]
        return positions

    async def modify_position(self, ticket: int, sl: float | None = None, tp: float | None = None) -> dict:
        logger.info(f"Modifying position {ticket}: sl={sl}, tp={tp}")
        result = await self.connector.modify_position(ticket, sl, tp)
        if result.get("success"):
            logger.info(f"Position {ticket} modified: sl={sl}, tp={tp}")
        else:
            logger.error(f"Modify position {ticket} failed: {result.get('error')}")
        return result
