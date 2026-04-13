"""
Integration tests for BotEngine — full trading loop with mocked dependencies.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from app.config import settings

import numpy as np
import pandas as pd
import pytest
import pytest_asyncio

from app.bot.engine import BotEngine, BotState
from app.constants import MIN_LOT, PAPER_INITIAL_BALANCE, WARMUP_SECONDS
from app.db.models import Trade


class TestBotEngine:
    @pytest_asyncio.fixture
    async def engine(self, mock_connector, db_session, redis_client):
        engine = BotEngine(
            connector=mock_connector,
            db_session=db_session,
            redis_client=redis_client,
            symbol="GOLD",
        )
        engine.paper_trade = True
        return engine

    async def test_initial_state(self, engine):
        assert engine.state == BotState.STOPPED

    async def test_start(self, engine):
        await engine.start()
        assert engine.state == BotState.RUNNING
        assert engine.started_at is not None

    async def test_stop(self, engine):
        await engine.start()
        await engine.stop()
        assert engine.state == BotState.STOPPED

    async def test_start_idempotent(self, engine):
        await engine.start()
        started = engine.started_at
        await engine.start()
        # Should not reset started_at
        assert engine.started_at == started

    async def test_emergency_stop(self, engine):
        await engine.start()
        result = await engine.emergency_stop()
        assert engine.state == BotState.STOPPED

    async def test_get_status(self, engine):
        status = engine.get_status()
        assert status["state"] == "STOPPED"
        assert status["strategy"] == "ema_crossover"
        assert status["symbol"] == "GOLD"
        assert "max_risk_per_trade" in status

    async def test_process_candle_when_stopped(self, engine):
        """Should return immediately when stopped."""
        await engine.process_candle()
        assert engine.state == BotState.STOPPED

    async def test_update_strategy(self, engine):
        await engine.update_strategy("breakout")
        assert engine.strategy.name == "breakout"

    async def test_update_settings(self, engine):
        await engine.update_settings(paper_trade=True, max_risk_per_trade=0.02)
        assert engine.paper_trade is True
        assert engine.risk_manager.max_risk_per_trade == 0.02

    async def test_update_settings_timeframe(self, engine):
        await engine.update_settings(timeframe="H1")
        assert engine.timeframe == "H1"

    async def test_update_settings_invalid_timeframe(self, engine):
        original = engine.timeframe
        await engine.update_settings(timeframe="INVALID")
        assert engine.timeframe == original

    async def test_paper_trade_mode(self, engine, make_ohlcv_df):
        """Paper trade should create virtual positions without calling real connector."""
        await engine.start()
        # Skip warmup
        engine.started_at = datetime.now(timezone.utc) - timedelta(hours=3)

        # Setup: mock market data to return a df that produces a signal
        df = make_ohlcv_df(rows=200, trend="up", base_price=2000.0)
        # Force a BUY signal on the second-to-last bar
        df.loc[df.index[-2], "signal"] = 1
        df["atr"] = 10.0

        engine.market_data.get_ohlcv = AsyncMock(return_value=df)
        engine.market_data.get_current_tick = AsyncMock(
            return_value={"ask": 2050.0, "bid": 2049.0}
        )
        engine.strategy.calculate = MagicMock(return_value=df)

        # Disable MTF filter to avoid H1 data dependency
        with patch.object(settings, "use_mtf_filter", False):
            await engine.process_candle()

        # Paper position should be created
        assert len(engine._paper_positions) == 1
        assert engine._paper_positions[0]["type"] == "BUY"
        assert engine._paper_positions[0]["symbol"] == "GOLD"

    async def test_circuit_breaker_pauses_bot(self, engine, redis_client):
        """When daily loss exceeds limit, bot should pause."""
        await engine.start()

        # Pre-load large loss into circuit breaker
        await redis_client.set(f"circuit:daily_pnl:GOLD", str(-500.0), ex=86400)

        await engine.process_candle()
        assert engine.state == BotState.PAUSED

    async def test_warmup_reduces_lot(self, engine):
        """Lot should be reduced during warmup period."""
        lot = engine._apply_warmup(1.0)
        # engine.started_at is None → no warmup applied
        assert lot == 1.0

        engine.started_at = datetime.now(timezone.utc)
        lot = engine._apply_warmup(1.0)
        # Just started → should be reduced
        assert lot < 1.0
        assert lot >= MIN_LOT


class TestBotEngineAutoResume:
    @pytest_asyncio.fixture
    async def engine(self, mock_connector, db_session, redis_client):
        engine = BotEngine(
            connector=mock_connector,
            db_session=db_session,
            redis_client=redis_client,
            symbol="GOLD",
        )
        return engine

    async def test_auto_resume_after_cooldown(self, engine, redis_client):
        """Paused bot should auto-resume after cooldown."""
        engine.state = BotState.PAUSED

        # Set trigger time to 2 hours ago (cooldown is 60 min default)
        past = datetime.now(timezone.utc) - timedelta(hours=2)
        await redis_client.set(
            f"circuit:triggered_at:GOLD",
            past.isoformat(),
            ex=86400,
        )

        await engine.process_candle()
        assert engine.state == BotState.RUNNING

    async def test_stays_paused_during_cooldown(self, engine, redis_client):
        """Paused bot should stay paused during cooldown."""
        engine.state = BotState.PAUSED

        # Set trigger time to 10 minutes ago
        recent = datetime.now(timezone.utc) - timedelta(minutes=10)
        await redis_client.set(
            f"circuit:triggered_at:GOLD",
            recent.isoformat(),
            ex=86400,
        )

        await engine.process_candle()
        assert engine.state == BotState.PAUSED
