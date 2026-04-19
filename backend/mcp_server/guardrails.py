"""
Trading guardrails — hard limits enforced at MCP broker tool level.

The agent CANNOT bypass these. Every broker.place_order() must pass through
validate_order() before execution.

State is tracked in Redis with TTL-based keys for automatic expiry.
"""

import os
import time
from dataclasses import dataclass
from datetime import UTC, datetime

import redis.asyncio as redis_lib

# ─── Hard Limits (non-negotiable) ────────────────────────────────────────────

# Position limits
MAX_LOT_PER_TRADE = 1.0
MAX_CONCURRENT_PER_SYMBOL = 3
MAX_CONCURRENT_TOTAL = 5

# Loss limits
MAX_DAILY_LOSS_PCT = 0.03
MAX_WEEKLY_LOSS_PCT = 0.07
CONSECUTIVE_LOSS_HALT = 5

# Execution limits
MAX_TRADES_PER_HOUR = 5
MIN_TIME_BETWEEN_TRADES = 120  # seconds
MAX_SPREAD_MULTIPLIER = 3.0

# Agent limits
MAX_AGENT_TURNS = 50
AGENT_TIMEOUT = 300  # seconds
MAX_DAILY_AGENT_CALLS = 200

# Token failure policy
ON_TOKEN_FAILURE = "pause"

# ─── Rollout Mode (Phase F) ─────────────────────────────────────────────────
# Controls execution behavior at the broker level.
# Set via ROLLOUT_MODE env var or config.settings.rollout_mode.

ROLLOUT_MODES = ("shadow", "paper", "micro", "live")
MICRO_MAX_LOT = 0.01  # Micro-live caps all orders at 0.01 lot

# ─── Redis Keys ──────────────────────────────────────────────────────────────

_KEY_PREFIX = "guardrails"


def _daily_key(name: str) -> str:
    date = datetime.now(UTC).strftime("%Y-%m-%d")
    return f"{_KEY_PREFIX}:{name}:{date}"


def _hourly_key(name: str) -> str:
    hour = datetime.now(UTC).strftime("%Y-%m-%dT%H")
    return f"{_KEY_PREFIX}:{name}:{hour}"


# ─── Validation Result ───────────────────────────────────────────────────────


@dataclass
class GuardrailResult:
    allowed: bool
    reason: str = ""


# ─── Guardrails Class ────────────────────────────────────────────────────────


class TradingGuardrails:
    """Enforces hard trading limits at the MCP tool level."""

    def __init__(self, redis: redis_lib.Redis):
        self.redis = redis

    def get_rollout_mode(self) -> str:
        """Get current rollout mode from env or default."""
        mode = os.environ.get("ROLLOUT_MODE", "shadow")
        return mode if mode in ROLLOUT_MODES else "shadow"

    async def set_rollout_mode(self, mode: str) -> None:
        """Persist rollout mode to Redis (survives restarts)."""
        if mode not in ROLLOUT_MODES:
            raise ValueError(f"Invalid rollout mode: {mode}. Must be one of {ROLLOUT_MODES}")
        await self.redis.set(f"{_KEY_PREFIX}:rollout_mode", mode)
        os.environ["ROLLOUT_MODE"] = mode

    async def get_persisted_rollout_mode(self) -> str:
        """Get rollout mode from Redis (or fall back to env)."""
        val = await self.redis.get(f"{_KEY_PREFIX}:rollout_mode")
        if val:
            mode = val.decode() if isinstance(val, bytes) else str(val)
            if mode in ROLLOUT_MODES:
                return mode
        return self.get_rollout_mode()

    def check_rollout_mode(self, lot: float) -> GuardrailResult:
        """Check if the current rollout mode allows execution, and enforce lot caps.

        Returns:
            GuardrailResult with allowed=True if execution should proceed,
            or allowed=False with reason for shadow/paper modes.
            For micro mode, the lot is capped but execution proceeds.
        """
        mode = self.get_rollout_mode()

        if mode == "shadow":
            return GuardrailResult(False, "SHADOW MODE: order logged but not executed")

        if mode == "paper":
            return GuardrailResult(False, "PAPER MODE: order simulated, not sent to broker")

        if mode == "micro":
            if lot > MICRO_MAX_LOT:
                return GuardrailResult(
                    True,  # allowed, but lot will be capped
                    f"MICRO MODE: lot capped from {lot} to {MICRO_MAX_LOT}",
                )
            return GuardrailResult(True)

        # mode == "live"
        return GuardrailResult(True)

    async def validate_order(
        self,
        symbol: str,
        lot: float,
        order_type: str,
        current_positions: list[dict],
        account_balance: float,
        daily_pnl: float,
        spread: float,
        avg_spread: float,
    ) -> GuardrailResult:
        """Validate a trade order against all guardrails.

        Args:
            symbol: Trading symbol (e.g., "GOLD")
            lot: Lot size for the order
            order_type: "BUY" or "SELL"
            current_positions: List of open positions [{symbol, lot, profit, ...}]
            account_balance: Current account balance
            daily_pnl: Today's realized P&L
            spread: Current spread in pips
            avg_spread: Average spread for this symbol
        """
        # 1. Max lot per trade
        if lot > MAX_LOT_PER_TRADE:
            return GuardrailResult(False, f"Lot {lot} exceeds max {MAX_LOT_PER_TRADE}")

        if lot <= 0:
            return GuardrailResult(False, f"Invalid lot size: {lot}")

        # 2. Max concurrent positions per symbol
        symbol_positions = [p for p in current_positions if p.get("symbol") == symbol]
        if len(symbol_positions) >= MAX_CONCURRENT_PER_SYMBOL:
            return GuardrailResult(
                False,
                f"{symbol}: {len(symbol_positions)} positions (max {MAX_CONCURRENT_PER_SYMBOL})",
            )

        # 3. Max concurrent positions total
        if len(current_positions) >= MAX_CONCURRENT_TOTAL:
            return GuardrailResult(
                False,
                f"Total positions {len(current_positions)} (max {MAX_CONCURRENT_TOTAL})",
            )

        # 4. Daily loss limit
        if account_balance > 0 and daily_pnl < 0:
            loss_pct = abs(daily_pnl) / account_balance
            if loss_pct >= MAX_DAILY_LOSS_PCT:
                return GuardrailResult(
                    False,
                    f"Daily loss {loss_pct:.1%} exceeds limit {MAX_DAILY_LOSS_PCT:.0%}",
                )

        # 5. Consecutive loss halt
        consecutive_losses = await self._get_consecutive_losses()
        if consecutive_losses >= CONSECUTIVE_LOSS_HALT:
            return GuardrailResult(
                False,
                f"{consecutive_losses} consecutive losses (halt at {CONSECUTIVE_LOSS_HALT})",
            )

        # 6. Trades per hour
        trades_this_hour = await self._get_trades_this_hour()
        if trades_this_hour >= MAX_TRADES_PER_HOUR:
            return GuardrailResult(
                False,
                f"{trades_this_hour} trades this hour (max {MAX_TRADES_PER_HOUR})",
            )

        # 7. Min time between trades
        last_trade_time = await self._get_last_trade_time()
        if last_trade_time:
            elapsed = time.time() - last_trade_time
            if elapsed < MIN_TIME_BETWEEN_TRADES:
                remaining = int(MIN_TIME_BETWEEN_TRADES - elapsed)
                return GuardrailResult(
                    False,
                    f"Too soon — wait {remaining}s (min {MIN_TIME_BETWEEN_TRADES}s between trades)",
                )

        # 8. Spread check
        if avg_spread > 0 and spread > avg_spread * MAX_SPREAD_MULTIPLIER:
            return GuardrailResult(
                False,
                f"Spread {spread:.1f} > {MAX_SPREAD_MULTIPLIER}x avg ({avg_spread:.1f})",
            )

        return GuardrailResult(True)

    async def validate_agent_call(self) -> GuardrailResult:
        """Check if the agent is within daily call limits."""
        calls_today = await self._get_daily_agent_calls()
        if calls_today >= MAX_DAILY_AGENT_CALLS:
            return GuardrailResult(
                False,
                f"Daily agent call limit reached: {calls_today}/{MAX_DAILY_AGENT_CALLS}",
            )
        return GuardrailResult(True)

    # ─── State Tracking ─────────────────────────────────────────────────────

    async def record_trade(self, is_win: bool) -> None:
        """Record a trade result for consecutive loss tracking."""
        key = _daily_key("trade_results")
        await self.redis.rpush(key, "1" if is_win else "0")
        await self.redis.expire(key, 86400 * 2)  # 2 days TTL

        # Update hourly counter
        hour_key = _hourly_key("trades")
        await self.redis.incr(hour_key)
        await self.redis.expire(hour_key, 3600)

        # Update last trade time
        await self.redis.set(f"{_KEY_PREFIX}:last_trade_time", str(time.time()))

    async def record_agent_call(self) -> None:
        """Increment daily agent call counter."""
        key = _daily_key("agent_calls")
        await self.redis.incr(key)
        await self.redis.expire(key, 86400 * 2)

    async def get_status(self) -> dict:
        """Get current guardrail state for monitoring."""
        return {
            "consecutive_losses": await self._get_consecutive_losses(),
            "trades_this_hour": await self._get_trades_this_hour(),
            "agent_calls_today": await self._get_daily_agent_calls(),
            "last_trade_time": await self._get_last_trade_time(),
            "limits": {
                "max_lot": MAX_LOT_PER_TRADE,
                "max_concurrent_symbol": MAX_CONCURRENT_PER_SYMBOL,
                "max_concurrent_total": MAX_CONCURRENT_TOTAL,
                "max_daily_loss_pct": MAX_DAILY_LOSS_PCT,
                "max_trades_per_hour": MAX_TRADES_PER_HOUR,
                "max_agent_calls": MAX_DAILY_AGENT_CALLS,
            },
        }

    # ─── Internal Helpers ────────────────────────────────────────────────────

    async def _get_consecutive_losses(self) -> int:
        """Count consecutive losses from the end of today's results."""
        key = _daily_key("trade_results")
        results = await self.redis.lrange(key, 0, -1)
        if not results:
            return 0

        count = 0
        for r in reversed(results):
            val = r.decode() if isinstance(r, bytes) else str(r)
            if val == "0":
                count += 1
            else:
                break
        return count

    async def _get_trades_this_hour(self) -> int:
        """Get trade count for the current hour."""
        key = _hourly_key("trades")
        val = await self.redis.get(key)
        return int(val) if val else 0

    async def _get_last_trade_time(self) -> float | None:
        """Get timestamp of last trade."""
        val = await self.redis.get(f"{_KEY_PREFIX}:last_trade_time")
        return float(val) if val else None

    async def _get_daily_agent_calls(self) -> int:
        """Get agent call count for today."""
        key = _daily_key("agent_calls")
        val = await self.redis.get(key)
        return int(val) if val else 0
