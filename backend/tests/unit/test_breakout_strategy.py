"""
Unit tests for Breakout Strategy.
"""

import numpy as np
import pandas as pd

from app.strategy.breakout import BreakoutStrategy


class TestBreakoutStrategy:
    def setup_method(self):
        self.strategy = BreakoutStrategy(lookback=20, atr_period=14, atr_threshold=0.5)

    def test_name(self):
        assert self.strategy.name == "breakout"

    def test_min_bars_required(self):
        assert self.strategy.min_bars_required == 39  # lookback + atr_period + 5

    def test_buy_signal_on_breakout(self):
        """Price breaks above N-period high channel → BUY (volume filter disabled)."""
        strategy = BreakoutStrategy(lookback=20, atr_period=14, atr_threshold=0.5, volume_filter=False)
        n = 80
        close = np.concatenate(
            [
                np.full(50, 100.0) + np.random.RandomState(42).randn(50) * 0.5,
                np.linspace(105, 160, 30),  # strong breakout
            ]
        )
        high = close + 1
        low = close - 1
        df = pd.DataFrame(
            {
                "time": pd.date_range("2025-01-01", periods=n, freq="15min"),
                "open": close,
                "high": high,
                "low": low,
                "close": close,
            }
        )
        result = strategy.calculate(df)
        buy_signals = result[result["signal"] == 1]
        assert len(buy_signals) > 0

    def test_sell_signal_on_breakdown(self):
        """Price breaks below N-period low channel → SELL (volume filter disabled)."""
        strategy = BreakoutStrategy(lookback=20, atr_period=14, atr_threshold=0.5, volume_filter=False)
        n = 80
        close = np.concatenate(
            [
                np.full(50, 100.0) + np.random.RandomState(42).randn(50) * 0.5,
                np.linspace(95, 40, 30),  # strong breakdown
            ]
        )
        high = close + 1
        low = close - 1
        df = pd.DataFrame(
            {
                "time": pd.date_range("2025-01-01", periods=n, freq="15min"),
                "open": close,
                "high": high,
                "low": low,
                "close": close,
            }
        )
        result = strategy.calculate(df)
        sell_signals = result[result["signal"] == -1]
        assert len(sell_signals) > 0

    def test_no_signal_in_range(self, make_ohlcv_df):
        """Flat market within range — no breakout."""
        df = make_ohlcv_df(rows=80, trend="flat", volatility=0.5)
        result = self.strategy.calculate(df)
        signals = result[result["signal"] != 0]
        assert len(signals) <= 3

    def test_no_volume_column_still_works(self):
        """Strategy should work without tick_volume column."""
        n = 60
        close = np.concatenate(
            [
                np.full(40, 100.0),
                np.linspace(100, 130, 20),
            ]
        )
        df = pd.DataFrame(
            {
                "time": pd.date_range("2025-01-01", periods=n, freq="15min"),
                "open": close,
                "high": close + 2,
                "low": close - 2,
                "close": close,
            }
        )
        strategy = BreakoutStrategy(lookback=20, volume_filter=True)
        result = strategy.calculate(df)
        assert "signal" in result.columns

    def test_volume_filter_toggle(self):
        """Volume filter disabled should still produce signals."""
        strategy = BreakoutStrategy(lookback=20, volume_filter=False)
        n = 60
        close = np.concatenate(
            [
                np.full(40, 100.0),
                np.linspace(100, 130, 20),
            ]
        )
        df = pd.DataFrame(
            {
                "time": pd.date_range("2025-01-01", periods=n, freq="15min"),
                "open": close,
                "high": close + 2,
                "low": close - 2,
                "close": close,
                "tick_volume": np.full(n, 500.0),
            }
        )
        result = strategy.calculate(df)
        assert "signal" in result.columns

    def test_signal_values(self, make_ohlcv_df):
        df = make_ohlcv_df(rows=80)
        result = self.strategy.calculate(df)
        assert set(result["signal"].unique()).issubset({-1, 0, 1})

    def test_columns_added(self, make_ohlcv_df):
        df = make_ohlcv_df(rows=80)
        result = self.strategy.calculate(df)
        assert "high_channel" in result.columns
        assert "low_channel" in result.columns
        assert "atr" in result.columns
