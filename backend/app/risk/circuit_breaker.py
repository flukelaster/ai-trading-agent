"""
Circuit Breaker — tracks daily P&L via Redis, halts trading when limit is reached.
"""

import json
from datetime import datetime, timezone

import redis.asyncio as redis
from loguru import logger

from app.config import settings


class CircuitBreaker:
    def __init__(self, redis_client: redis.Redis, symbol: str = "GOLD"):
        self.redis = redis_client
        self.symbol = symbol
        self.pnl_key = f"circuit:daily_pnl:{symbol}"
        self.trade_count_key = f"circuit:trade_count:{symbol}"

    async def record_trade_result(self, profit: float) -> None:
        current = await self.redis.get(self.pnl_key)
        current_pnl = float(current) if current else 0.0
        new_pnl = current_pnl + profit
        # TTL: seconds until next midnight UTC
        ttl = self._seconds_until_midnight()
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
            logger.warning(f"Circuit breaker [{self.symbol}] TRIGGERED: daily_pnl={daily_pnl:.2f}, limit=-{max_loss:.2f}")
        return triggered

    async def reset(self) -> None:
        await self.redis.delete(self.pnl_key, self.trade_count_key)
        logger.info(f"Circuit breaker [{self.symbol}] reset")

    @staticmethod
    def _seconds_until_midnight() -> int:
        now = datetime.now(timezone.utc)
        midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
        if now >= midnight:
            from datetime import timedelta
            midnight += timedelta(days=1)
        return max(int((midnight - now).total_seconds()), 60)
