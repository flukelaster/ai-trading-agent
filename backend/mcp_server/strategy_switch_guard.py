"""
Strategy Switch Guard — enforces safety limits on AI auto-strategy switching.

Redis-backed: cooldown, daily rate limit, feature flag check.
Pattern follows guardrails.py + param_gate.py.
"""

from dataclasses import dataclass
from datetime import UTC, datetime

import redis.asyncio as redis_lib
from loguru import logger

_KEY_PREFIX = "strategy_switch"

COOLDOWN_SECONDS = 3600  # 1 hour between switches
MAX_DAILY_SWITCHES = 3


def _decode(val: bytes | str | None) -> str | None:
    """Decode a Redis value that may be bytes, str, or None."""
    if val is None:
        return None
    return val.decode() if isinstance(val, bytes) else str(val)


@dataclass
class SwitchResult:
    allowed: bool
    reason: str = ""


class StrategySwitchGuard:
    """Enforces safety guardrails for AI auto-strategy switching."""

    def __init__(self, redis: redis_lib.Redis):
        self.redis = redis

    async def is_enabled(self) -> bool:
        """Check if auto-strategy-switch feature flag is ON."""
        val = await self.redis.get("enable_auto_strategy_switch")
        return _decode(val) == "1"

    async def validate_switch(
        self,
        symbol: str,
        to_strategy: str,
    ) -> SwitchResult:
        """Validate whether a strategy switch is allowed.

        Checks: feature flag, cooldown, daily limit, same-strategy guard.
        """
        # Fetch all guard keys in one pipeline round-trip
        today = datetime.now(UTC).strftime("%Y-%m-%d")
        pipe = self.redis.pipeline()
        pipe.get("enable_auto_strategy_switch")
        pipe.get(f"{_KEY_PREFIX}:current:{symbol}")
        pipe.get(f"{_KEY_PREFIX}:last:{symbol}")
        pipe.get(f"{_KEY_PREFIX}:count:{today}")
        enabled_raw, current_raw, last_raw, count_raw = await pipe.execute()

        # 1. Feature flag
        if _decode(enabled_raw) != "1":
            return SwitchResult(False, "Auto strategy switch is disabled (feature flag OFF)")

        # 2. Market open check
        try:
            from app.bot.scheduler import is_market_open

            if not is_market_open(symbol):
                return SwitchResult(False, f"Market closed for {symbol}")
        except ImportError:
            pass  # Skip in tests — scheduler imports MT5/APScheduler deps

        # 3. Same-strategy guard
        current_name = _decode(current_raw)
        if current_name and current_name == to_strategy:
            return SwitchResult(False, f"Already using {to_strategy} for {symbol}")

        # 4. Cooldown check (1 hour)
        last_str = _decode(last_raw)
        if last_str:
            elapsed = datetime.now(UTC).timestamp() - float(last_str)
            if elapsed < COOLDOWN_SECONDS:
                remaining = int(COOLDOWN_SECONDS - elapsed)
                return SwitchResult(
                    False,
                    f"Cooldown active: {remaining}s remaining (min {COOLDOWN_SECONDS}s between switches)",
                )

        # 5. Daily limit
        daily_count = int(_decode(count_raw)) if count_raw else 0
        if daily_count >= MAX_DAILY_SWITCHES:
            return SwitchResult(
                False,
                f"Daily limit reached: {daily_count}/{MAX_DAILY_SWITCHES} switches today",
            )

        return SwitchResult(True)

    async def record_switch(
        self,
        symbol: str,
        strategy_name: str,
        reasoning: str = "",
    ) -> None:
        """Record a successful strategy switch in Redis."""
        now = datetime.now(UTC)
        today = now.strftime("%Y-%m-%d")
        count_key = f"{_KEY_PREFIX}:count:{today}"

        pipe = self.redis.pipeline()
        pipe.set(f"{_KEY_PREFIX}:last:{symbol}", str(now.timestamp()))
        pipe.set(f"{_KEY_PREFIX}:current:{symbol}", strategy_name)
        pipe.incr(count_key)
        pipe.expire(count_key, 86400)  # TTL 24h
        await pipe.execute()

        logger.info(
            f"Strategy switch recorded [{symbol}]: → {strategy_name} "
            f"| reason: {reasoning[:100]}"
        )

    async def get_status(self, symbol: str) -> dict:
        """Get current switch guard status for a symbol."""
        today = datetime.now(UTC).strftime("%Y-%m-%d")
        pipe = self.redis.pipeline()
        pipe.get("enable_auto_strategy_switch")
        pipe.get(f"{_KEY_PREFIX}:current:{symbol}")
        pipe.get(f"{_KEY_PREFIX}:last:{symbol}")
        pipe.get(f"{_KEY_PREFIX}:count:{today}")
        enabled_raw, current_raw, last_raw, count_raw = await pipe.execute()

        enabled = _decode(enabled_raw) == "1"
        current_strategy = _decode(current_raw)

        last_switch = None
        cooldown_remaining = 0
        last_str = _decode(last_raw)
        if last_str:
            last_time = float(last_str)
            last_switch = datetime.fromtimestamp(last_time, tz=UTC).isoformat()
            elapsed = datetime.now(UTC).timestamp() - last_time
            cooldown_remaining = max(0, int(COOLDOWN_SECONDS - elapsed))

        daily_count = int(_decode(count_raw)) if count_raw else 0

        return {
            "enabled": enabled,
            "current_strategy": current_strategy,
            "last_switch": last_switch,
            "cooldown_remaining_s": cooldown_remaining,
            "daily_switches": daily_count,
            "max_daily": MAX_DAILY_SWITCHES,
            "cooldown_s": COOLDOWN_SECONDS,
        }
