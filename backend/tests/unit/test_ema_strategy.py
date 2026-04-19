"""
Unit tests for EMA Crossover Strategy.
"""

import pandas as pd

from app.strategy.ema_crossover import EMACrossoverStrategy


class TestEMACrossoverStrategy:
    def setup_method(self):
        self.strategy = EMACrossoverStrategy(fast_period=20, slow_period=50)

    def test_name(self):
        assert self.strategy.name == "ema_crossover"

    def test_min_bars_required(self):
        assert self.strategy.min_bars_required == 55  # slow_period + 5

    def test_get_params(self):
        params = self.strategy.get_params()
        assert params["fast_period"] == 20
        assert params["slow_period"] == 50

    def test_buy_signal_on_crossover(self, make_crossover_df):
        df = make_crossover_df(crossover_type="bullish")
        result = self.strategy.calculate(df)
        buy_signals = result[result["signal"] == 1]
        assert len(buy_signals) > 0, "Expected at least one BUY signal on bullish crossover"

    def test_sell_signal_on_crossover(self, make_crossover_df):
        df = make_crossover_df(crossover_type="bearish")
        result = self.strategy.calculate(df)
        sell_signals = result[result["signal"] == -1]
        assert len(sell_signals) > 0, "Expected at least one SELL signal on bearish crossover"

    def test_no_signal_flat_market(self):
        # Constant price → EMAs are identical → no crossover
        n = 100
        df = pd.DataFrame(
            {
                "time": pd.date_range("2025-01-01", periods=n, freq="15min"),
                "open": [2000.0] * n,
                "high": [2001.0] * n,
                "low": [1999.0] * n,
                "close": [2000.0] * n,
            }
        )
        result = self.strategy.calculate(df)
        signals = result[result["signal"] != 0]
        assert len(signals) == 0, "Constant price should produce zero crossovers"

    def test_signal_column_exists(self, make_ohlcv_df):
        df = make_ohlcv_df(rows=100)
        result = self.strategy.calculate(df)
        assert "signal" in result.columns
        assert "atr" in result.columns
        assert "ema_fast" in result.columns
        assert "ema_slow" in result.columns

    def test_signal_values(self, make_ohlcv_df):
        df = make_ohlcv_df(rows=100)
        result = self.strategy.calculate(df)
        assert set(result["signal"].unique()).issubset({-1, 0, 1})

    def test_insufficient_bars(self):
        # Only 10 bars — less than min_bars_required
        df = pd.DataFrame(
            {
                "time": pd.date_range("2025-01-01", periods=10, freq="15min"),
                "open": [100.0] * 10,
                "high": [101.0] * 10,
                "low": [99.0] * 10,
                "close": [100.0] * 10,
            }
        )
        result = self.strategy.calculate(df)
        assert "signal" in result.columns
        # Should not crash, signals should be 0
        assert (result["signal"] == 0).all()

    def test_does_not_mutate_input(self, make_ohlcv_df):
        df = make_ohlcv_df(rows=100)
        original_cols = set(df.columns)
        self.strategy.calculate(df)
        assert set(df.columns) == original_cols

    def test_custom_periods(self, make_crossover_df):
        strategy = EMACrossoverStrategy(fast_period=5, slow_period=20)
        df = make_crossover_df(crossover_type="bullish", fast_period=5, slow_period=20)
        result = strategy.calculate(df)
        assert "signal" in result.columns
