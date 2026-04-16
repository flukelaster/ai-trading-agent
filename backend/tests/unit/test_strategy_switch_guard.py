"""
Unit tests for strategy switch guard — cooldown, rate limit, feature flag.
"""

from datetime import UTC, datetime

import pytest
import pytest_asyncio

from mcp_server.strategy_switch_guard import (
    COOLDOWN_SECONDS,
    MAX_DAILY_SWITCHES,
    StrategySwitchGuard,
)


@pytest_asyncio.fixture
async def guard(redis_client):
    return StrategySwitchGuard(redis_client)


# ─── Feature flag ───────────────────────────────────────────────────────────


class TestFeatureFlag:
    @pytest.mark.asyncio
    async def test_disabled_by_default(self, guard):
        result = await guard.is_enabled()
        assert result is False

    @pytest.mark.asyncio
    async def test_enable_via_redis(self, guard):
        await guard.redis.set("enable_auto_strategy_switch", "1")
        assert await guard.is_enabled() is True

    @pytest.mark.asyncio
    async def test_disable_via_redis(self, guard):
        await guard.redis.set("enable_auto_strategy_switch", "0")
        assert await guard.is_enabled() is False


# ─── Validate switch ────────────────────────────────────────────────────────
# Note: is_market_open check is skipped in tests because app.bot.scheduler
# cannot be imported without full app context. The guard catches ImportError.


class TestValidateSwitch:
    @pytest.mark.asyncio
    async def test_rejects_when_disabled(self, guard):
        result = await guard.validate_switch("GOLD", "breakout")
        assert not result.allowed
        assert "feature flag OFF" in result.reason

    @pytest.mark.asyncio
    async def test_allows_when_enabled(self, guard):
        await guard.redis.set("enable_auto_strategy_switch", "1")
        result = await guard.validate_switch("GOLD", "breakout")
        assert result.allowed

    @pytest.mark.asyncio
    async def test_rejects_same_strategy(self, guard):
        await guard.redis.set("enable_auto_strategy_switch", "1")
        await guard.redis.set("strategy_switch:current:GOLD", "breakout")
        result = await guard.validate_switch("GOLD", "breakout")
        assert not result.allowed
        assert "Already using" in result.reason

    @pytest.mark.asyncio
    async def test_allows_different_strategy(self, guard):
        await guard.redis.set("enable_auto_strategy_switch", "1")
        await guard.redis.set("strategy_switch:current:GOLD", "ema_crossover")
        result = await guard.validate_switch("GOLD", "breakout")
        assert result.allowed

    @pytest.mark.asyncio
    async def test_rejects_during_cooldown(self, guard):
        await guard.redis.set("enable_auto_strategy_switch", "1")
        now = datetime.now(UTC).timestamp()
        await guard.redis.set("strategy_switch:last:GOLD", str(now - 10))
        result = await guard.validate_switch("GOLD", "breakout")
        assert not result.allowed
        assert "Cooldown" in result.reason

    @pytest.mark.asyncio
    async def test_allows_after_cooldown(self, guard):
        await guard.redis.set("enable_auto_strategy_switch", "1")
        now = datetime.now(UTC).timestamp()
        await guard.redis.set("strategy_switch:last:GOLD", str(now - 7200))
        result = await guard.validate_switch("GOLD", "breakout")
        assert result.allowed

    @pytest.mark.asyncio
    async def test_rejects_at_daily_limit(self, guard):
        await guard.redis.set("enable_auto_strategy_switch", "1")
        today = datetime.now(UTC).strftime("%Y-%m-%d")
        await guard.redis.set(f"strategy_switch:count:{today}", str(MAX_DAILY_SWITCHES))
        result = await guard.validate_switch("GOLD", "breakout")
        assert not result.allowed
        assert "Daily limit" in result.reason

    @pytest.mark.asyncio
    async def test_allows_under_daily_limit(self, guard):
        await guard.redis.set("enable_auto_strategy_switch", "1")
        today = datetime.now(UTC).strftime("%Y-%m-%d")
        await guard.redis.set(f"strategy_switch:count:{today}", str(MAX_DAILY_SWITCHES - 1))
        result = await guard.validate_switch("GOLD", "breakout")
        assert result.allowed


# ─── Record switch ──────────────────────────────────────────────────────────


class TestRecordSwitch:
    @pytest.mark.asyncio
    async def test_records_switch(self, guard):
        await guard.record_switch("GOLD", "breakout", "Regime changed to trending")

        current = await guard.redis.get("strategy_switch:current:GOLD")
        assert current is not None
        current_name = current.decode() if isinstance(current, bytes) else str(current)
        assert current_name == "breakout"

        last = await guard.redis.get("strategy_switch:last:GOLD")
        assert last is not None

        today = datetime.now(UTC).strftime("%Y-%m-%d")
        count = await guard.redis.get(f"strategy_switch:count:{today}")
        assert count is not None
        count_val = int(count.decode() if isinstance(count, bytes) else str(count))
        assert count_val == 1

    @pytest.mark.asyncio
    async def test_increments_daily_counter(self, guard):
        await guard.record_switch("GOLD", "breakout", "reason1")
        await guard.record_switch("GOLD", "ema_crossover", "reason2")

        today = datetime.now(UTC).strftime("%Y-%m-%d")
        count = await guard.redis.get(f"strategy_switch:count:{today}")
        count_val = int(count.decode() if isinstance(count, bytes) else str(count))
        assert count_val == 2


# ─── Get status ─────────────────────────────────────────────────────────────


class TestGetStatus:
    @pytest.mark.asyncio
    async def test_default_status(self, guard):
        status = await guard.get_status("GOLD")
        assert status["enabled"] is False
        assert status["current_strategy"] is None
        assert status["daily_switches"] == 0
        assert status["max_daily"] == MAX_DAILY_SWITCHES
        assert status["cooldown_s"] == COOLDOWN_SECONDS

    @pytest.mark.asyncio
    async def test_status_after_switch(self, guard):
        await guard.redis.set("enable_auto_strategy_switch", "1")
        await guard.record_switch("GOLD", "breakout", "trending detected")

        status = await guard.get_status("GOLD")
        assert status["enabled"] is True
        assert status["current_strategy"] == "breakout"
        assert status["daily_switches"] == 1
        assert status["last_switch"] is not None
        assert status["cooldown_remaining_s"] > 0
