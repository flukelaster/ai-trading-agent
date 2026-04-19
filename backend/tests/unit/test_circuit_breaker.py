"""
Unit tests for Circuit Breaker — daily PnL tracking, trigger, cooldown, reset.
"""

from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio

from app.constants import MIN_TTL_SECONDS
from app.market.sessions import get_reset_hour
from app.risk.circuit_breaker import CircuitBreaker


class TestCircuitBreaker:
    @pytest_asyncio.fixture
    async def cb(self, redis_client):
        return CircuitBreaker(redis_client, symbol="GOLD", cooldown_minutes=60)

    async def test_record_trade_result(self, cb):
        await cb.record_trade_result(100.0)
        pnl = await cb.get_daily_pnl()
        assert pnl == pytest.approx(100.0)

    async def test_record_multiple_trades(self, cb):
        await cb.record_trade_result(100.0)
        await cb.record_trade_result(-50.0)
        pnl = await cb.get_daily_pnl()
        assert pnl == pytest.approx(50.0)

    async def test_trade_count(self, cb):
        await cb.record_trade_result(10.0)
        await cb.record_trade_result(-5.0)
        count = await cb.get_trade_count()
        assert count == 2

    async def test_not_triggered_within_limit(self, cb):
        await cb.record_trade_result(-100.0)
        # Balance 10000, max_daily_loss 0.03 → limit is -300
        triggered = await cb.is_triggered(balance=10000)
        assert triggered is False

    async def test_triggered_exceeds_limit(self, cb):
        await cb.record_trade_result(-350.0)
        # -350 < -300 → triggered
        triggered = await cb.is_triggered(balance=10000)
        assert triggered is True

    async def test_can_resume_no_trigger(self, cb):
        # No trigger recorded → can resume
        result = await cb.can_resume()
        assert result is True

    async def test_can_resume_before_cooldown(self, cb, redis_client):
        # Set trigger time to now
        await redis_client.set(
            cb.triggered_key,
            datetime.now(UTC).isoformat(),
            ex=86400,
        )
        result = await cb.can_resume()
        assert result is False

    async def test_can_resume_after_cooldown(self, cb, redis_client):
        # Set trigger time to 2 hours ago (cooldown is 60 min)
        past = datetime.now(UTC) - timedelta(hours=2)
        await redis_client.set(
            cb.triggered_key,
            past.isoformat(),
            ex=86400,
        )
        result = await cb.can_resume()
        assert result is True

    async def test_reset_clears_keys(self, cb, redis_client):
        await cb.record_trade_result(-100.0)
        await cb.reset()
        pnl = await cb.get_daily_pnl()
        count = await cb.get_trade_count()
        assert pnl == 0.0
        assert count == 0

    async def test_initial_pnl_zero(self, cb):
        pnl = await cb.get_daily_pnl()
        assert pnl == 0.0

    async def test_initial_count_zero(self, cb):
        count = await cb.get_trade_count()
        assert count == 0


class TestCircuitBreakerGlobal:
    async def test_global_pnl_sum(self, redis_client):
        cb_gold = CircuitBreaker(redis_client, "GOLD")
        cb_oil = CircuitBreaker(redis_client, "OILCash")
        await cb_gold.record_trade_result(-100.0)
        await cb_oil.record_trade_result(-50.0)
        total = await CircuitBreaker.get_global_daily_pnl(redis_client, ["GOLD", "OILCash"])
        assert total == pytest.approx(-150.0)

    async def test_global_triggered(self, redis_client):
        cb = CircuitBreaker(redis_client, "GOLD")
        await cb.record_trade_result(-1100.0)
        triggered = await CircuitBreaker.is_global_triggered(
            redis_client,
            ["GOLD"],
            balance=10000,
            max_portfolio_loss=0.10,
        )
        assert triggered is True

    async def test_global_not_triggered(self, redis_client):
        cb = CircuitBreaker(redis_client, "GOLD")
        await cb.record_trade_result(-50.0)
        triggered = await CircuitBreaker.is_global_triggered(
            redis_client,
            ["GOLD"],
            balance=10000,
            max_portfolio_loss=0.10,
        )
        assert triggered is False


class TestSecondsUntilReset:
    def test_returns_positive(self):
        seconds = CircuitBreaker._seconds_until_reset("GOLD")
        assert seconds >= MIN_TTL_SECONDS

    def test_metal_reset_hour(self):
        # GOLD → metal asset class → reset at 22:00 UTC
        assert get_reset_hour("metal") == 22

    def test_crypto_reset_hour(self):
        assert get_reset_hour("crypto") == 0

    def test_unknown_symbol_defaults_to_zero(self):
        # Unknown symbol → defaults to hour 0
        seconds = CircuitBreaker._seconds_until_reset("UNKNOWN")
        assert seconds >= MIN_TTL_SECONDS
