"""
BotManager — coordinates multiple BotEngine instances, one per symbol.
"""

import asyncio
import time

import redis.asyncio as redis
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.engine import BotEngine
from app.config import SYMBOL_PROFILES, apply_db_symbol_profiles, settings
from app.db.session import async_session
from app.mt5.connector import MT5BridgeConnector
from app.services import symbol_config_service as symbol_svc
from app.services.symbol_config_service import RELOAD_CHANNEL


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
        self._reload_task: asyncio.Task | None = None
        self._sentiment_analyzer = None
        self._notifier = None
        self._binance_connector = None
        # Prefer DB-sourced enable flags; fall back to env-var symbol list when empty.
        db_enabled = [
            s for s, p in SYMBOL_PROFILES.items()
            if p.get("is_enabled") is True and "canonical" not in p
        ]
        initial = db_enabled or settings.symbol_list
        for symbol in initial:
            if symbol not in SYMBOL_PROFILES:
                logger.warning(f"BotManager: Symbol '{symbol}' missing from SYMBOL_PROFILES — using defaults (review contract_size!)")

        for symbol in initial:
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
            "enable_auto_strategy_switch": settings.enable_auto_strategy_switch,
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

    async def get_portfolio_exposure(self, balance: float) -> dict:
        """Calculate total notional exposure across all symbols."""
        positions_by_sym = await self.get_active_positions()
        total_notional = 0.0
        symbol_exposure: dict[str, float] = {}

        for symbol, positions in positions_by_sym.items():
            profile = SYMBOL_PROFILES.get(symbol, {})
            contract_size = profile.get("contract_size", 1)
            sym_notional = 0.0
            for pos in positions:
                notional = abs(pos.get("lot", 0) * pos.get("current_price", 0) * contract_size)
                sym_notional += notional
            symbol_exposure[symbol] = sym_notional
            total_notional += sym_notional

        leverage = total_notional / balance if balance > 0 else 0
        return {
            "total_notional": total_notional,
            "leverage": leverage,
            "symbol_exposure": symbol_exposure,
        }

    async def check_portfolio_limit(self, balance: float, max_leverage: float = 3.0) -> tuple[bool, str]:
        """Check if portfolio exposure exceeds max leverage. Returns (can_trade, reason)."""
        exposure = await self.get_portfolio_exposure(balance)
        if exposure["leverage"] >= max_leverage:
            reason = f"Portfolio leverage {exposure['leverage']:.1f}x exceeds limit {max_leverage:.1f}x"
            logger.warning(reason)
            return False, reason
        return True, "OK"

    def _build_engine(self, symbol: str, profile: dict) -> BotEngine:
        engine = BotEngine(
            connector=self.connector,
            db_session=self.db,
            redis_client=self.redis,
            symbol=symbol,
            symbol_profile=profile,
        )
        engine._manager = self
        if self._sentiment_analyzer:
            engine.set_sentiment_analyzer(self._sentiment_analyzer)
        if self._notifier:
            engine.set_notifier(self._notifier)
        return engine

    async def reload_engines(self) -> dict:
        """Rebuild engine set from current SYMBOL_PROFILES + is_enabled flags."""
        enabled = {
            s for s, p in SYMBOL_PROFILES.items()
            if p.get("is_enabled") is True and "canonical" not in p
        }
        if not enabled:
            # Backward compat: fall back to env-var symbol list when DB empty.
            enabled = set(settings.symbol_list)

        current = set(self.engines.keys())
        to_add = enabled - current
        to_remove = current - enabled
        to_update = enabled & current

        stop_coros = [self.engines.pop(s).stop() for s in to_remove]
        if stop_coros:
            await asyncio.gather(*stop_coros, return_exceptions=True)

        for symbol in to_add:
            try:
                self.engines[symbol] = self._build_engine(symbol, SYMBOL_PROFILES.get(symbol, {}))
            except Exception as e:
                logger.error(f"BotManager: create {symbol} failed: {e}")

        for symbol in to_update:
            profile = SYMBOL_PROFILES.get(symbol)
            if profile:
                self.engines[symbol].apply_profile(profile)

        summary = {
            "added": sorted(to_add),
            "removed": sorted(to_remove),
            "updated": sorted(to_update),
            "active": sorted(self.engines.keys()),
        }
        logger.info(f"BotManager reload: {summary}")
        return summary

    async def _apply_db_and_reload(self) -> None:
        async with async_session() as session:
            db_profiles = await symbol_svc.load_profiles_from_db(session)
        apply_db_symbol_profiles(db_profiles)
        await self.reload_engines()

    async def start_reload_subscriber(self, debounce_seconds: float = 0.3) -> None:
        """Subscribe to Redis reload channel; coalesce bursts within debounce window."""
        if self._reload_task and not self._reload_task.done():
            return

        async def _run() -> None:
            backoff = 1.0
            while True:
                pubsub = self.redis.pubsub()
                try:
                    await pubsub.subscribe(RELOAD_CHANNEL)
                    logger.info(f"BotManager: subscribed to {RELOAD_CHANNEL}")
                    backoff = 1.0
                    async for msg in pubsub.listen():
                        if msg.get("type") != "message":
                            continue
                        # Drain any additional messages that arrived in the debounce window
                        await asyncio.sleep(debounce_seconds)
                        while True:
                            extra = await pubsub.get_message(ignore_subscribe_messages=True, timeout=0.01)
                            if not extra:
                                break
                        try:
                            await self._apply_db_and_reload()
                        except Exception as e:
                            logger.error(f"BotManager reload handler failed: {e}")
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    logger.warning(f"BotManager subscriber error (retrying in {backoff:.0f}s): {e}")
                    await asyncio.sleep(backoff)
                    backoff = min(backoff * 2, 60.0)
                finally:
                    try:
                        await pubsub.unsubscribe(RELOAD_CHANNEL)
                        await pubsub.aclose()
                    except Exception:
                        pass

        self._reload_task = asyncio.create_task(_run())

    async def stop_reload_subscriber(self) -> None:
        if self._reload_task and not self._reload_task.done():
            self._reload_task.cancel()
            try:
                await self._reload_task
            except (asyncio.CancelledError, Exception):
                pass

    def set_sentiment_analyzer(self, analyzer, symbol: str | None = None):
        """Set sentiment analyzer on one or all engines."""
        if symbol:
            engine = self.engines.get(symbol)
            if engine:
                engine.set_sentiment_analyzer(analyzer)
        else:
            self._sentiment_analyzer = analyzer
            for engine in self.engines.values():
                engine.set_sentiment_analyzer(analyzer)

    def set_notifier(self, notifier, symbol: str | None = None):
        """Set Telegram notifier on one or all engines."""
        if symbol:
            engine = self.engines.get(symbol)
            if engine:
                engine.set_notifier(notifier)
        else:
            self._notifier = notifier
            for engine in self.engines.values():
                engine.set_notifier(notifier)
