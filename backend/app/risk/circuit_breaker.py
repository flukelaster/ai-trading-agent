"""
Circuit Breaker — tracks daily P&L via Redis, halts trading when limit is reached.
Supports per-symbol market hour reset and cooldown-based auto-recovery.

Reset hour is derived from the symbol's asset_class via app.market.sessions so
user-added symbols inherit the correct daily reset without hardcoded lookups.
"""

import json
from datetime import datetime, timezone

import redis.asyncio as redis
from loguru import logger

from app.config import SYMBOL_PROFILES, settings
from app.constants import DEFAULT_MAX_DRAWDOWN_FROM_PEAK, DEFAULT_PORTFOLIO_MAX_LOSS, MIN_TTL_SECONDS
from app.market.sessions import seconds_until_reset

# Cooldown period before auto-recovery (minutes)
DEFAULT_COOLDOWN_MINUTES = 60


def _asset_class_for(symbol: str) -> str | None:
    profile = SYMBOL_PROFILES.get(symbol) or {}
    return profile.get("asset_class")


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

        # Early warning at 80% of daily loss limit (once per day)
        if not triggered and daily_pnl <= -(max_loss * 0.8):
            warn_key = f"circuit:drawdown_warned:{self.symbol}"
            already_warned = await self.redis.get(warn_key)
            if not already_warned:
                ttl = self._seconds_until_reset(self.symbol)
                await self.redis.set(warn_key, "1", ex=ttl)
                logger.warning(
                    f"Drawdown warning [{self.symbol}]: daily_pnl={daily_pnl:.2f} "
                    f"({abs(daily_pnl / max_loss) * 100:.0f}% of limit)"
                )

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
    async def is_global_triggered(redis_client, symbols: list[str], balance: float, max_portfolio_loss: float = DEFAULT_PORTFOLIO_MAX_LOSS) -> bool:
        """Check if total daily loss across all symbols exceeds portfolio limit."""
        total_pnl = await CircuitBreaker.get_global_daily_pnl(redis_client, symbols)
        max_loss = balance * max_portfolio_loss
        triggered = total_pnl <= -max_loss
        if triggered:
            logger.warning(f"GLOBAL circuit breaker TRIGGERED: total_pnl={total_pnl:.2f}, limit=-{max_loss:.2f}")
        return triggered

    @staticmethod
    async def update_peak_balance(redis_client, balance: float) -> float:
        """Track peak balance in Redis (no TTL — persists across restarts)."""
        key = "circuit:peak_balance"
        current = await redis_client.get(key)
        peak = float(current) if current else 0.0
        if balance > peak:
            peak = balance
            await redis_client.set(key, str(peak))
        return peak

    @staticmethod
    async def is_drawdown_halted(
        redis_client, balance: float,
        max_drawdown_pct: float = DEFAULT_MAX_DRAWDOWN_FROM_PEAK,
    ) -> bool:
        """Check if balance dropped > X% from peak. Returns True to halt trading."""
        peak = await CircuitBreaker.update_peak_balance(redis_client, balance)
        if peak <= 0:
            return False
        drawdown_pct = (peak - balance) / peak
        if drawdown_pct >= max_drawdown_pct:
            logger.warning(
                f"ABSOLUTE DRAWDOWN HALT: balance={balance:.2f}, peak={peak:.2f}, "
                f"drawdown={drawdown_pct:.1%} >= limit={max_drawdown_pct:.1%}"
            )
            return True
        return False

    @staticmethod
    def _seconds_until_reset(symbol: str) -> int:
        """Seconds until daily reset, derived from the symbol's asset class."""
        asset_class = _asset_class_for(symbol)
        # Strip timezone info — sessions.seconds_until_reset uses naive UTC internally
        now_naive = datetime.now(timezone.utc).replace(tzinfo=None)
        return max(seconds_until_reset(asset_class, now=now_naive), MIN_TTL_SECONDS)
