"""
Order Executor — places and manages orders via MT5 Bridge.
"""

from loguru import logger

from app.mt5.connector import MT5BridgeConnector


class OrderExecutor:
    def __init__(self, connector: MT5BridgeConnector):
        self.connector = connector

    async def place_order(
        self, symbol: str, order_type: str, lot: float, sl: float, tp: float, comment: str = "", magic: int = 234000
    ) -> dict:
        logger.info(f"Placing order: {order_type} {lot} {symbol} SL={sl} TP={tp}")
        result = await self.connector.place_order(symbol, order_type, lot, sl, tp, comment, magic)
        if result.get("success"):
            logger.info(f"Order placed: ticket={result['data'].get('ticket')}")
        else:
            logger.error(f"Order failed: {result.get('error')}")
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
        logger.warning(f"Closing ALL positions (symbol={symbol})")
        result = await self.connector.close_all_positions(symbol=symbol)
        return result

    async def get_open_positions(self, symbol: str | None = None) -> list[dict]:
        result = await self.connector.get_positions()
        if not result.get("success"):
            return []
        positions = result.get("data", [])
        if symbol:
            positions = [p for p in positions if p.get("symbol") == symbol]
        return positions

    async def modify_position(self, ticket: int, sl: float | None = None, tp: float | None = None) -> dict:
        logger.info(f"Modifying position {ticket}: sl={sl}, tp={tp}")
        result = await self.connector.modify_position(ticket, sl, tp)
        if result.get("success"):
            logger.info(f"Position {ticket} modified: sl={sl}, tp={tp}")
        else:
            logger.error(f"Modify position {ticket} failed: {result.get('error')}")
        return result
