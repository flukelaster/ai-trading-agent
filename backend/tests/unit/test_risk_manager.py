"""
Unit tests for Risk Manager — lot sizing, SL/TP, trade permission.
"""

import pytest

from app.constants import (
    HIGH_VOL_THRESHOLD,
    LOW_VOL_THRESHOLD,
    MIN_LOT,
    STREAK_2_FACTOR,
    STREAK_3_FACTOR,
)
from app.risk.manager import RiskManager


class TestCalculateLotSize:
    def setup_method(self):
        self.rm = RiskManager(
            max_risk_per_trade=0.01,
            max_lot=1.0,
            pip_value=1.0,
        )

    def test_basic_lot_size(self):
        lot = self.rm.calculate_lot_size(balance=10000, sl_pips=20)
        assert lot > 0
        assert lot <= self.rm.max_lot

    def test_zero_sl_returns_min_lot(self):
        lot = self.rm.calculate_lot_size(balance=10000, sl_pips=0)
        assert lot == MIN_LOT

    def test_negative_sl_returns_min_lot(self):
        lot = self.rm.calculate_lot_size(balance=10000, sl_pips=-5)
        assert lot == MIN_LOT

    def test_lot_capped_at_max(self):
        rm = RiskManager(max_risk_per_trade=0.5, max_lot=0.5)
        lot = rm.calculate_lot_size(balance=100000, sl_pips=1)
        assert lot <= 0.5

    def test_lot_floor_at_min(self):
        lot = self.rm.calculate_lot_size(balance=10, sl_pips=100)
        assert lot == MIN_LOT

    def test_high_volatility_reduces_lot(self):
        lot_normal = self.rm.calculate_lot_size(balance=10000, sl_pips=20, atr_pct=None)
        lot_high_vol = self.rm.calculate_lot_size(balance=10000, sl_pips=20, atr_pct=HIGH_VOL_THRESHOLD + 0.1)
        assert lot_high_vol <= lot_normal

    def test_low_volatility_increases_lot(self):
        lot_normal = self.rm.calculate_lot_size(balance=10000, sl_pips=20, atr_pct=0.3)
        lot_low_vol = self.rm.calculate_lot_size(balance=10000, sl_pips=20, atr_pct=LOW_VOL_THRESHOLD - 0.1)
        assert lot_low_vol >= lot_normal

    def test_slippage_and_commission(self):
        lot_default = self.rm.calculate_lot_size(balance=10000, sl_pips=20)
        lot_high_slip = self.rm.calculate_lot_size(balance=10000, sl_pips=20, slippage_pips=10.0)
        assert lot_high_slip < lot_default

    def test_custom_pip_value(self):
        lot = self.rm.calculate_lot_size(balance=10000, sl_pips=20, pip_value=10.0)
        lot_default = self.rm.calculate_lot_size(balance=10000, sl_pips=20, pip_value=1.0)
        assert lot < lot_default  # higher pip_value → smaller lot


class TestCalculateKellySize:
    def setup_method(self):
        self.rm = RiskManager(max_risk_per_trade=0.01, max_lot=1.0, pip_value=1.0)

    def test_kelly_basic(self):
        lot = self.rm.calculate_kelly_size(
            balance=10000,
            sl_pips=20,
            win_rate=0.6,
            avg_win=100,
            avg_loss=50,
        )
        assert lot > 0
        assert lot <= self.rm.max_lot

    def test_kelly_zero_loss_falls_back(self):
        lot = self.rm.calculate_kelly_size(
            balance=10000,
            sl_pips=20,
            win_rate=0.6,
            avg_win=100,
            avg_loss=0,
        )
        # Falls back to calculate_lot_size
        expected = self.rm.calculate_lot_size(balance=10000, sl_pips=20)
        assert lot == expected

    def test_kelly_zero_win_rate_falls_back(self):
        lot = self.rm.calculate_kelly_size(
            balance=10000,
            sl_pips=20,
            win_rate=0,
            avg_win=100,
            avg_loss=50,
        )
        expected = self.rm.calculate_lot_size(balance=10000, sl_pips=20)
        assert lot == expected

    def test_kelly_negative_kelly_uses_min(self):
        # Bad strategy: low win rate
        lot = self.rm.calculate_kelly_size(
            balance=10000,
            sl_pips=20,
            win_rate=0.2,
            avg_win=10,
            avg_loss=100,
        )
        # Should still return a valid lot
        assert lot >= MIN_LOT

    def test_kelly_capped_at_max_risk(self):
        lot = self.rm.calculate_kelly_size(
            balance=10000,
            sl_pips=20,
            win_rate=0.9,
            avg_win=500,
            avg_loss=10,
        )
        # Should not exceed max_lot
        assert lot <= self.rm.max_lot

    def test_kelly_zero_sl(self):
        lot = self.rm.calculate_kelly_size(
            balance=10000,
            sl_pips=0,
            win_rate=0.6,
            avg_win=100,
            avg_loss=50,
        )
        assert lot == MIN_LOT


class TestAdjustForStreak:
    def setup_method(self):
        self.rm = RiskManager()

    def test_3_losses_halves_lot(self):
        result = self.rm.adjust_for_streak(0.10, consecutive_losses=3, consecutive_wins=0)
        assert result == pytest.approx(0.10 * STREAK_3_FACTOR, abs=0.01)

    def test_2_losses_75_pct(self):
        result = self.rm.adjust_for_streak(0.10, consecutive_losses=2, consecutive_wins=0)
        assert result == pytest.approx(0.10 * STREAK_2_FACTOR, abs=0.01)

    def test_0_losses_no_change(self):
        result = self.rm.adjust_for_streak(0.10, consecutive_losses=0, consecutive_wins=0)
        assert result == 0.10

    def test_1_loss_no_change(self):
        result = self.rm.adjust_for_streak(0.10, consecutive_losses=1, consecutive_wins=0)
        assert result == 0.10

    def test_floor_at_min_lot(self):
        result = self.rm.adjust_for_streak(MIN_LOT, consecutive_losses=0, consecutive_wins=0)
        assert result >= MIN_LOT


class TestCalculateSLTP:
    def setup_method(self):
        self.rm = RiskManager(sl_atr_mult=1.5, tp_atr_mult=2.0, price_decimals=2)

    def test_buy_sl_below_entry(self):
        result = self.rm.calculate_sl_tp(entry_price=2000, signal=1, atr=10)
        assert result.sl < 2000
        assert result.tp > 2000

    def test_sell_sl_above_entry(self):
        result = self.rm.calculate_sl_tp(entry_price=2000, signal=-1, atr=10)
        assert result.sl > 2000
        assert result.tp < 2000

    def test_buy_distances(self):
        result = self.rm.calculate_sl_tp(entry_price=2000, signal=1, atr=10)
        assert result.sl == pytest.approx(2000 - 15, abs=0.01)  # 1.5 * 10
        assert result.tp == pytest.approx(2000 + 20, abs=0.01)  # 2.0 * 10

    def test_sell_distances(self):
        result = self.rm.calculate_sl_tp(entry_price=2000, signal=-1, atr=10)
        assert result.sl == pytest.approx(2000 + 15, abs=0.01)
        assert result.tp == pytest.approx(2000 - 20, abs=0.01)

    def test_custom_multipliers(self):
        result = self.rm.calculate_sl_tp(entry_price=100, signal=1, atr=5, sl_mult=2.0, tp_mult=3.0)
        assert result.sl == pytest.approx(100 - 10, abs=0.01)
        assert result.tp == pytest.approx(100 + 15, abs=0.01)


class TestCanOpenTrade:
    def setup_method(self):
        self.rm = RiskManager(
            max_concurrent_trades=3,
            max_daily_loss=0.03,
            use_ai_filter=True,
            ai_confidence_threshold=0.7,
        )

    def test_allowed_when_ok(self):
        allowed, reason = self.rm.can_open_trade(
            current_positions=0,
            daily_pnl=0,
            balance=10000,
        )
        assert allowed is True
        assert reason == "OK"

    def test_max_positions_reached(self):
        allowed, reason = self.rm.can_open_trade(
            current_positions=3,
            daily_pnl=0,
            balance=10000,
        )
        assert allowed is False
        assert "Max concurrent trades" in reason

    def test_daily_loss_limit(self):
        # Daily loss = -300 >= -(10000 * 0.03) = -300
        allowed, reason = self.rm.can_open_trade(
            current_positions=0,
            daily_pnl=-300,
            balance=10000,
        )
        assert allowed is False
        assert "Daily loss limit" in reason

    def test_ai_filter_blocks_buy_on_bearish(self):
        allowed, reason = self.rm.can_open_trade(
            current_positions=0,
            daily_pnl=0,
            balance=10000,
            signal=1,
            ai_sentiment={"label": "bearish", "confidence": 0.8},
        )
        assert allowed is False
        assert "bearish" in reason

    def test_ai_filter_blocks_sell_on_bullish(self):
        allowed, reason = self.rm.can_open_trade(
            current_positions=0,
            daily_pnl=0,
            balance=10000,
            signal=-1,
            ai_sentiment={"label": "bullish", "confidence": 0.8},
        )
        assert allowed is False
        assert "bullish" in reason

    def test_ai_filter_allows_buy_on_bullish(self):
        allowed, reason = self.rm.can_open_trade(
            current_positions=0,
            daily_pnl=0,
            balance=10000,
            signal=1,
            ai_sentiment={"label": "bullish", "confidence": 0.8},
        )
        assert allowed is True

    def test_ai_filter_low_confidence_allows(self):
        allowed, reason = self.rm.can_open_trade(
            current_positions=0,
            daily_pnl=0,
            balance=10000,
            signal=1,
            ai_sentiment={"label": "bearish", "confidence": 0.5},
        )
        # Confidence 0.5 < threshold 0.7 → should allow
        assert allowed is True

    def test_ai_filter_disabled(self):
        rm = RiskManager(use_ai_filter=False)
        allowed, reason = rm.can_open_trade(
            current_positions=0,
            daily_pnl=0,
            balance=10000,
            signal=1,
            ai_sentiment={"label": "bearish", "confidence": 0.9},
        )
        assert allowed is True

    def test_no_signal_bypasses_ai(self):
        allowed, reason = self.rm.can_open_trade(
            current_positions=0,
            daily_pnl=0,
            balance=10000,
            signal=0,
            ai_sentiment={"label": "bearish", "confidence": 0.9},
        )
        assert allowed is True
