"""
Regression tests for bugs found during the Nov 2026 review.

Each test reproduces a failure that existed on main before the fix:

1. walk_forward_test() crashed with AttributeError (OptimizationResult.results).
2. ProcessRunnerBackend.get_logs() crashed slicing a deque when ``since`` was None.
3. broker tools imported a non-existent ``app.bot.manager.get_manager`` so AI
   trades were never written to the event log.
4. Consecutive-loss halt could never fire — every open recorded a "win" and
   no close ever recorded a loss.
5. Broker read rollout mode from the env var, ignoring a Redis-persisted UI
   downgrade (e.g. live → paper).
6. Daily-loss guardrail only looked at the traded symbol's P&L instead of the
   account-wide total.
"""

import json
from collections import deque
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pandas as pd
import pytest

from mcp_server.guardrails import CONSECUTIVE_LOSS_HALT, TradingGuardrails

# ─── 1. Walk-forward ────────────────────────────────────────────────────────


def _synthetic_ohlcv(n: int = 1500) -> pd.DataFrame:
    rng = np.random.default_rng(0)
    close = 2000 + np.cumsum(rng.normal(0, 3, n))
    return pd.DataFrame(
        {
            "time": pd.date_range("2025-01-01", periods=n, freq="h"),
            "open": close,
            "high": close + 2,
            "low": close - 2,
            "close": close,
            "tick_volume": 1000,
        }
    )


def test_walk_forward_runs_end_to_end():
    from app.backtest.walk_forward import walk_forward_test

    result = walk_forward_test(
        "ema_crossover",
        _synthetic_ohlcv(),
        {"fast_period": [5, 10], "slow_period": [20, 30]},
        n_splits=3,
        min_trades=1,
    )
    assert result.n_splits == 3
    assert len(result.windows) > 0
    assert "params" in result.windows[0] or "best_params" in result.windows[0]
    json.dumps(result.to_dict())  # must be JSON-serialisable for the API response


# ─── 2. Runner log buffer ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_process_runner_get_logs_with_deque_buffer():
    from app.runner.backend import LogEntry, ProcessInfo, ProcessRunnerBackend

    backend = ProcessRunnerBackend()
    now = datetime.utcnow()
    info = ProcessInfo(process=MagicMock(), pid=1, started_at=now)
    assert isinstance(info.log_buffer, deque)
    for i in range(10):
        info.log_buffer.append(LogEntry(timestamp=now + timedelta(seconds=i), level="info", message=f"m{i}"))
    backend._processes[7] = info

    logs = await backend.get_logs(7, limit=3)
    assert [e.message for e in logs] == ["m7", "m8", "m9"]

    logs = await backend.get_logs(7, since=now + timedelta(seconds=5), limit=100)
    assert [e.message for e in logs] == ["m5", "m6", "m7", "m8", "m9"]

    assert await backend.get_logs(7, limit=0) == []


# ─── Broker helpers ─────────────────────────────────────────────────────────


def _connector(balance=10000.0, positions=None, close_profit=0.0):
    c = AsyncMock()
    c.get_account.return_value = {"success": True, "data": {"balance": balance, "profit": 0}}
    c.get_positions.return_value = {"success": True, "data": positions or []}
    c.get_tick.return_value = {"success": True, "data": {"ask": 2450.0, "bid": 2449.5}}
    c.place_order.return_value = {"success": True, "data": {"ticket": 1, "price": 2450.0}}
    c.close_position.return_value = {"success": True}
    return c


@pytest.fixture
def broker_env(redis_client, monkeypatch):
    """Wire the broker module to fakeredis + real guardrails, then restore."""
    from mcp_server.tools import broker

    saved = (broker._connector, broker._guardrails, broker._notifier, broker._redis)
    broker._guardrails = TradingGuardrails(redis_client)
    broker._redis = redis_client
    broker._notifier = None
    monkeypatch.setenv("ROLLOUT_MODE", "live")
    yield broker
    broker._connector, broker._guardrails, broker._notifier, broker._redis = saved


# ─── 3. Event log import path ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_ai_trade_is_written_to_event_log(broker_env):
    broker = broker_env
    broker._connector = _connector()

    engine = MagicMock()
    engine._log_event = AsyncMock()
    manager = MagicMock()
    manager.engines = {"GOLD": engine}

    with patch("app.api.routes.bot._manager", manager):
        result = await broker.place_order("GOLD", "BUY", 0.1, 2440, 2470)

    assert result["executed"] is True
    engine._log_event.assert_awaited_once()


# ─── 4. Consecutive-loss halt ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_opening_an_order_does_not_record_a_win(broker_env, redis_client):
    broker = broker_env
    broker._connector = _connector()
    g = broker._guardrails

    for _ in range(CONSECUTIVE_LOSS_HALT - 1):
        await g.record_result(is_win=False)

    await broker.place_order("GOLD", "BUY", 0.1, 2440, 2470)

    # Streak must survive the open — previously reset to 0 by a fake "win".
    assert await g._get_consecutive_losses() == CONSECUTIVE_LOSS_HALT - 1
    assert await g._get_trades_this_hour() == 1


@pytest.mark.asyncio
async def test_losing_closes_trigger_halt(broker_env):
    broker = broker_env
    g = broker._guardrails

    for ticket in range(CONSECUTIVE_LOSS_HALT):
        broker._connector = _connector(positions=[{"ticket": ticket, "symbol": "GOLD", "profit": -25.0}])
        res = await broker.close_position(ticket)
        assert res["closed"] is True

    assert await g._get_consecutive_losses() == CONSECUTIVE_LOSS_HALT
    verdict = await g.validate_order("GOLD", 0.1, "BUY", [], 10000, 0, 0.5, 0.5)
    assert verdict.allowed is False
    assert "consecutive losses" in verdict.reason


@pytest.mark.asyncio
async def test_winning_close_resets_streak(broker_env):
    broker = broker_env
    g = broker._guardrails
    await g.record_result(is_win=False)
    await g.record_result(is_win=False)

    broker._connector = _connector(positions=[{"ticket": 9, "symbol": "GOLD", "profit": 40.0}])
    await broker.close_position(9)
    assert await g._get_consecutive_losses() == 0


@pytest.mark.asyncio
async def test_record_trade_backcompat(redis_client):
    g = TradingGuardrails(redis_client)
    await g.record_trade(is_win=False)
    assert await g._get_consecutive_losses() == 1
    assert await g._get_trades_this_hour() == 1


# ─── 5. Rollout mode: Redis wins over env ───────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize("persisted", ["shadow", "paper"])
async def test_ui_downgrade_blocks_real_orders(broker_env, persisted):
    broker = broker_env  # env says ROLLOUT_MODE=live
    broker._connector = _connector()
    await broker._guardrails.redis.set("guardrails:rollout_mode", persisted)

    result = await broker.place_order("GOLD", "BUY", 0.1, 2440, 2470)

    assert result["mode"] == persisted
    broker._connector.place_order.assert_not_called()


@pytest.mark.asyncio
async def test_ui_downgrade_blocks_close_and_modify(broker_env):
    broker = broker_env
    broker._connector = _connector(positions=[{"ticket": 5, "symbol": "GOLD", "profit": 1.0}])
    await broker._guardrails.redis.set("guardrails:rollout_mode", "shadow")

    assert (await broker.close_position(5))["closed"] is False
    assert (await broker.modify_position(5, sl=2400))["modified"] is False
    broker._connector.close_position.assert_not_called()
    broker._connector.modify_position.assert_not_called()


# ─── 6. Account-wide daily loss ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_daily_loss_limit_is_account_wide(broker_env, redis_client):
    broker = broker_env
    broker._connector = _connector(balance=10000.0)
    # 2% + 1.5% across two OTHER symbols = 3.5% > 3% account limit
    await redis_client.set("circuit:daily_pnl:GOLD", "-200")
    await redis_client.set("circuit:daily_pnl:OILCash", "-150")

    result = await broker.place_order("BTCUSD", "BUY", 0.1, 2440, 2470)

    assert result.get("rejected") is True
    assert "Daily loss" in result["reason"]
    broker._connector.place_order.assert_not_called()


@pytest.mark.asyncio
async def test_account_daily_pnl_sums_symbols(redis_client):
    from mcp_server.tools.broker import _account_daily_pnl

    await redis_client.set("circuit:daily_pnl:GOLD", "-200")
    await redis_client.set("circuit:daily_pnl:OILCash", "50.5")
    await redis_client.set("circuit:trade_count:GOLD", "9")  # must be ignored
    assert await _account_daily_pnl(redis_client) == pytest.approx(-149.5)
