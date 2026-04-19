"""
Unit tests for technical indicators — pure function tests.
"""

import numpy as np
import pandas as pd
import pytest

from app.strategy.indicators import adx, atr, bollinger_bands, ema, rsi, stochastic


class TestEMA:
    def test_ema_basic(self):
        series = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0])
        result = ema(series, 3)
        assert len(result) == 5
        assert result.iloc[-1] > result.iloc[0]  # uptrend

    def test_ema_constant(self):
        series = pd.Series([10.0] * 20)
        result = ema(series, 5)
        np.testing.assert_allclose(result.values, 10.0, atol=1e-10)

    def test_ema_length_1(self):
        series = pd.Series([1.0, 2.0, 3.0])
        result = ema(series, 1)
        pd.testing.assert_series_equal(result, series)

    def test_ema_follows_trend(self):
        up = pd.Series(np.linspace(100, 200, 50))
        result = ema(up, 10)
        # EMA should lag behind the uptrend
        assert result.iloc[-1] < up.iloc[-1]
        assert result.iloc[-1] > up.iloc[0]


class TestRSI:
    def test_rsi_all_gains(self):
        series = pd.Series(np.linspace(100, 200, 30))
        result = rsi(series, 14)
        # All gains → RSI near 100
        assert result.iloc[-1] > 90

    def test_rsi_all_losses(self):
        series = pd.Series(np.linspace(200, 100, 30))
        result = rsi(series, 14)
        # All losses → RSI near 0
        assert result.iloc[-1] < 10

    def test_rsi_range(self):
        np.random.seed(42)
        series = pd.Series(np.random.randn(100).cumsum() + 100)
        result = rsi(series, 14)
        valid = result.dropna()
        assert (valid >= 0).all()
        assert (valid <= 100).all()

    def test_rsi_equal_gains_losses(self):
        # Alternating up/down should give RSI around 50
        series = pd.Series([100 + (i % 2) * 2 for i in range(50)], dtype=float)
        result = rsi(series, 14)
        assert 30 < result.iloc[-1] < 70


class TestATR:
    def test_atr_basic(self):
        n = 30
        high = pd.Series(np.full(n, 105.0))
        low = pd.Series(np.full(n, 95.0))
        close = pd.Series(np.full(n, 100.0))
        result = atr(high, low, close, 14)
        # Constant range → ATR converges to 10
        assert abs(result.iloc[-1] - 10.0) < 1.0

    def test_atr_positive(self):
        np.random.seed(42)
        close = pd.Series(np.random.randn(50).cumsum() + 100)
        high = close + abs(np.random.randn(50)) * 2
        low = close - abs(np.random.randn(50)) * 2
        result = atr(high, low, close, 14)
        valid = result.dropna()
        assert (valid > 0).all()


class TestADX:
    def test_adx_trending(self):
        # Strong uptrend → ADX should be high
        n = 60
        close = pd.Series(np.linspace(100, 200, n))
        high = close + 2
        low = close - 2
        result = adx(high, low, close, 14)
        assert result["adx"].iloc[-1] > 20

    def test_adx_flat(self):
        # Flat market → ADX should be low
        n = 60
        np.random.seed(42)
        close = pd.Series(100 + np.random.randn(n) * 0.5)
        high = close + 0.5
        low = close - 0.5
        result = adx(high, low, close, 14)
        assert result["adx"].iloc[-1] < 40

    def test_adx_returns_all_keys(self):
        n = 30
        close = pd.Series(np.linspace(100, 120, n))
        high = close + 1
        low = close - 1
        result = adx(high, low, close, 14)
        assert "adx" in result
        assert "di_plus" in result
        assert "di_minus" in result


class TestBollingerBands:
    def test_bb_contains_price(self):
        np.random.seed(42)
        series = pd.Series(np.random.randn(50).cumsum() + 100)
        result = bollinger_bands(series, 20, 2.0)
        # Most prices should be within bands
        valid_idx = result["upper"].dropna().index
        within = (series[valid_idx] <= result["upper"][valid_idx]) & (series[valid_idx] >= result["lower"][valid_idx])
        assert within.sum() / len(within) > 0.8

    def test_bb_bandwidth_positive(self):
        series = pd.Series(np.linspace(100, 110, 30))
        result = bollinger_bands(series, 20, 2.0)
        valid = result["bandwidth"].dropna()
        assert (valid >= 0).all()

    def test_bb_pct_b_range(self):
        np.random.seed(42)
        series = pd.Series(np.random.randn(50).cumsum() + 100)
        result = bollinger_bands(series, 20, 2.0)
        # %B should mostly be between 0 and 1
        valid = result["pct_b"].dropna()
        assert valid.median() > 0
        assert valid.median() < 1


class TestStochastic:
    def test_stochastic_at_high(self):
        # Close at the high of the range
        n = 20
        high = pd.Series(np.full(n, 110.0))
        low = pd.Series(np.full(n, 90.0))
        close = pd.Series(np.full(n, 110.0))
        result = stochastic(high, low, close, 14, 3)
        assert result["k"].iloc[-1] == pytest.approx(100.0)

    def test_stochastic_at_low(self):
        n = 20
        high = pd.Series(np.full(n, 110.0))
        low = pd.Series(np.full(n, 90.0))
        close = pd.Series(np.full(n, 90.0))
        result = stochastic(high, low, close, 14, 3)
        assert result["k"].iloc[-1] == pytest.approx(0.0)

    def test_stochastic_returns_k_and_d(self):
        n = 20
        high = pd.Series(np.linspace(105, 115, n))
        low = pd.Series(np.linspace(95, 105, n))
        close = pd.Series(np.linspace(100, 110, n))
        result = stochastic(high, low, close, 14, 3)
        assert "k" in result
        assert "d" in result
