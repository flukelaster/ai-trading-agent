"""
Circuit Breaker — tracks daily P&L via Redis, halts trading when limit is reached.
Supports per-symbol market hour reset and cooldown-based auto-recovery.
"""

import json
from datetime import datetime, timedelta, timezone

import redis.asyncio as redis
from loguru import logger

from app.config import settings

# Market hours reset time (UTC) per symbol type
# Forex/metals reset at 17:00 EST = 22:00 UTC (21:00 during DST)
# Crypto is 24/7, reset at midnight UTC
MARKET_RESET_HOURS = {
    "GOLD": 22,
    "XAUUSD": 22,
    "OILCash": 22,
    "USDJPY": 22,
    "EURUSD": 22,
    "GBPUSD": 22,
    "BTCUSD": 0,
    "ETHUSD": 0,
}

# Cooldown period before auto-recovery (minutes)
DEFAULT_COOLDOWN_MINUTES = 60


class CircuitBreaker:
    def __init__(self, redis_client: redis.Redis, symbol: str = "GOLD", cooldown_minutes: int = DEFAULT_COOLDOWN_MINUTES):
        self.redis = redis_client
        self.symbol = symbol
        self.pnl_key = f"circuit:daily_pnl:{symbol}"
        self.trade_count_key = f"circuit:trade_count:{symbol}"
        self.triggered_key = f"circuit:triggered_at:{symbol}"
        self.cooldown_minutes = cooldown_minutes

    async def record_trade_result(self, profit: float) -> None:
        current = await self.redis.get(self.pnl_key)
        current_pnl = float(current) if current else 0.0
        new_pnl = current_pnl + profit
        ttl = self._seconds_until_reset(self.symbol)
        await self.redis.set(self.pnl_key, str(new_pnl), ex=ttl)

        count = await self.redis.get(self.trade_count_key)
        new_count = int(count) + 1 if count else 1
        await self.redis.set(self.trade_count_key, str(new_count), ex=ttl)

        logger.info(f"Circuit breaker [{self.symbol}]: recorded profit={profit:.2f}, daily_pnl={new_pnl:.2f}, trades={new_count}")

    async def get_daily_pnl(self) -> float:
        val = await self.redis.get(self.pnl_key)
        return float(val) if val else 0.0

    async def get_trade_count(self) -> int:
        val = await self.redis.get(self.trade_count_key)
        return int(val) if val else 0

    async def is_triggered(self, balance: float) -> bool:
        daily_pnl = await self.get_daily_pnl()
        max_loss = balance * settings.max_daily_loss
        triggered = daily_pnl <= -max_loss
        if triggered:
            # Record trigger time for cooldown
            await self.redis.set(self.triggered_key, datetime.now(timezone.utc).isoformat(), ex=86400)
            logger.warning(f"Circuit breaker [{self.symbol}] TRIGGERED: daily_pnl={daily_pnl:.2f}, limit=-{max_loss:.2f}")
        return triggered

    async def can_resume(self) -> bool:
        """Check if enough cooldown time has passed to allow auto-recovery."""
        triggered_at_str = await self.redis.get(self.triggered_key)
        if not triggered_at_str:
            return True

        try:
            triggered_at = datetime.fromisoformat(triggered_at_str.decode() if isinstance(triggered_at_str, bytes) else triggered_at_str)
            if triggered_at.tzinfo is None:
                triggered_at = triggered_at.replace(tzinfo=timezone.utc)
        except (ValueError, TypeError):
            return True

        elapsed = (datetime.now(timezone.utc) - triggered_at).total_seconds() / 60
        if elapsed < self.cooldown_minutes:
            logger.debug(f"Circuit breaker [{self.symbol}] cooldown: {self.cooldown_minutes - elapsed:.0f}m remaining")
            return False

        # Cooldown passed, clear trigger
        await self.redis.delete(self.triggered_key)
        logger.info(f"Circuit breaker [{self.symbol}] cooldown complete — ready to resume")
        return True

    async def reset(self) -> None:
        await self.redis.delete(self.pnl_key, self.trade_count_key, self.triggered_key)
        logger.info(f"Circuit breaker [{self.symbol}] reset")

    @staticmethod
    async def get_global_daily_pnl(redis_client, symbols: list[str]) -> float:
        """Sum daily PnL across all symbols for portfolio-level risk check."""
        keys = [f"circuit:daily_pnl:{symbol}" for symbol in symbols]
        values = await redis_client.mget(keys)
        return sum(float(v) for v in values if v)

    @staticmethod
    async def is_global_triggered(redis_client, symbols: list[str], balance: float, max_portfolio_loss: float = 0.10) -> bool:
        """Check if total daily loss across all symbols exceeds portfolio limit."""
        total_pnl = await CircuitBreaker.get_global_daily_pnl(redis_client, symbols)
        max_loss = balance * max_portfolio_loss
        triggered = total_pnl <= -max_loss
        if triggered:
            logger.warning(f"GLOBAL circuit breaker TRIGGERED: total_pnl={total_pnl:.2f}, limit=-{max_loss:.2f}")
        return triggered

    @staticmethod
    def _seconds_until_reset(symbol: str) -> int:
        """Calculate seconds until daily reset based on symbol's market hours."""
        reset_hour = MARKET_RESET_HOURS.get(symbol, 0)
        now = datetime.now(timezone.utc)
        reset_time = now.replace(hour=reset_hour, minute=0, second=0, microsecond=0)
        if now >= reset_time:
            reset_time += timedelta(days=1)
        return max(int((reset_time - now).total_seconds()), 60)
