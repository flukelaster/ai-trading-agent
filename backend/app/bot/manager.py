"""
BotManager — coordinates multiple BotEngine instances, one per symbol.
"""

import asyncio
import time

import redis.asyncio as redis
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.engine import BotEngine
from app.config import SYMBOL_PROFILES, settings
from app.mt5.connector import MT5BridgeConnector


class BotManager:
    """Manages one BotEngine per configured symbol, sharing infrastructure."""

    def __init__(
        self,
        connector: MT5BridgeConnector,
        db_session: AsyncSession,
        redis_client: redis.Redis,
    ):
        self.connector = connector
        self.db = db_session
        self.redis = redis_client
        self.engines: dict[str, BotEngine] = {}
        self._positions_cache: dict[str, list[dict]] = {}
        self._positions_cache_time: float = 0

        # Create an engine for each configured symbol
        for symbol in settings.symbol_list:
            profile = SYMBOL_PROFILES.get(symbol, {})
            engine = BotEngine(
                connector=connector,
                db_session=db_session,
                redis_client=redis_client,
                symbol=symbol,
                symbol_profile=profile,
            )
            engine._manager = self
            self.engines[symbol] = engine
            logger.info(f"BotManager: created engine for {symbol} ({profile.get('display_name', symbol)})")

    def get_engine(self, symbol: str) -> BotEngine | None:
        return self.engines.get(symbol)

    def get_symbols(self) -> list[str]:
        return list(self.engines.keys())

    async def start(self, symbol: str | None = None):
        """Start one or all engines."""
        if symbol:
            engine = self.engines.get(symbol)
            if engine:
                await engine.start()
            else:
                logger.warning(f"BotManager: unknown symbol {symbol}")
        else:
            await asyncio.gather(*(e.start() for e in self.engines.values()))

    async def stop(self, symbol: str | None = None):
        """Stop one or all engines."""
        if symbol:
            engine = self.engines.get(symbol)
            if engine:
                await engine.stop()
        else:
            await asyncio.gather(*(e.stop() for e in self.engines.values()))

    async def emergency_stop(self, symbol: str | None = None) -> dict:
        """Emergency stop — close all positions for one or all symbols."""
        results = {}
        if symbol:
            engine = self.engines.get(symbol)
            if engine:
                results[symbol] = await engine.emergency_stop()
        else:
            for sym, engine in self.engines.items():
                results[sym] = await engine.emergency_stop()
        return results

    def get_status(self, symbol: str | None = None) -> dict:
        """Get status for one symbol or aggregate for all."""
        if symbol:
            engine = self.engines.get(symbol)
            return engine.get_status() if engine else {}

        symbols_status = {}
        for sym, engine in self.engines.items():
            status = engine.get_status()
            profile = SYMBOL_PROFILES.get(sym, {})
            status["display_name"] = profile.get("display_name", sym)
            symbols_status[sym] = status

        running = sum(1 for e in self.engines.values() if e.state.value == "RUNNING")
        return {
            "symbols": symbols_status,
            "active_count": running,
            "total_count": len(self.engines),
        }

    async def get_active_positions(self) -> dict[str, list[dict]]:
        """Get open positions grouped by symbol (cached 30s)."""
        now = time.time()
        if now - self._positions_cache_time < 30 and self._positions_cache:
            return self._positions_cache
        result = {}
        for symbol, engine in self.engines.items():
            try:
                positions = await engine.executor.get_open_positions(symbol)
                if positions:
                    result[symbol] = positions
            except Exception:
                pass
        self._positions_cache = result
        self._positions_cache_time = now
        return result

    def set_sentiment_analyzer(self, analyzer, symbol: str | None = None):
        """Set sentiment analyzer on one or all engines."""
        if symbol:
            engine = self.engines.get(symbol)
            if engine:
                engine.set_sentiment_analyzer(analyzer)
        else:
            for engine in self.engines.values():
                engine.set_sentiment_analyzer(analyzer)

    def set_notifier(self, notifier, symbol: str | None = None):
        """Set Telegram notifier on one or all engines."""
        if symbol:
            engine = self.engines.get(symbol)
            if engine:
                engine.set_notifier(notifier)
        else:
            for engine in self.engines.values():
                engine.set_notifier(notifier)
