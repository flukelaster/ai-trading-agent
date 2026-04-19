"""
Unit tests for ML Strategy.
"""

from unittest.mock import MagicMock

import numpy as np

from app.strategy.ml_strategy import MLStrategy


class TestMLStrategy:
    def test_name(self):
        strategy = MLStrategy(model_path="nonexistent.pkl")
        assert strategy.name == "ml_signal"

    def test_min_bars_required(self):
        strategy = MLStrategy(model_path="nonexistent.pkl")
        assert strategy.min_bars_required == 200

    def test_no_model_returns_zeros(self, make_ohlcv_df):
        """When no model is loaded, all signals should be 0."""
        strategy = MLStrategy(model_path="nonexistent.pkl")
        df = make_ohlcv_df(rows=250)
        result = strategy.calculate(df)
        assert "signal" in result.columns
        assert (result["signal"] == 0).all()

    def test_signal_with_mock_model(self, make_ohlcv_df):
        """Inject a mock model that returns fixed probabilities."""
        strategy = MLStrategy(model_path="nonexistent.pkl", confidence_threshold=0.5)

        # Create a mock model
        mock_model = MagicMock()
        # Return BUY (class 2) with high confidence for all rows
        mock_model.predict.return_value = np.array([[0.1, 0.1, 0.8]] * 250)

        strategy._model = mock_model
        strategy._model_loaded = True

        df = make_ohlcv_df(rows=250)
        result = strategy.calculate(df)
        buy_signals = result[result["signal"] == 1]
        assert len(buy_signals) > 0, "Mock model returning BUY with 80% confidence should produce signals"

    def test_low_confidence_no_signal(self, make_ohlcv_df):
        """Model confidence below threshold → no signal."""
        strategy = MLStrategy(model_path="nonexistent.pkl", confidence_threshold=0.9)

        mock_model = MagicMock()
        # 50% confidence → below 0.9 threshold
        mock_model.predict.return_value = np.array([[0.3, 0.2, 0.5]] * 250)

        strategy._model = mock_model
        strategy._model_loaded = True

        df = make_ohlcv_df(rows=250)
        result = strategy.calculate(df)
        signals = result[result["signal"] != 0]
        assert len(signals) == 0, "Low confidence should not produce signals"

    def test_sell_signal(self, make_ohlcv_df):
        """Model predicting SELL (class 0) with high confidence."""
        strategy = MLStrategy(model_path="nonexistent.pkl", confidence_threshold=0.5)

        mock_model = MagicMock()
        mock_model.predict.return_value = np.array([[0.8, 0.1, 0.1]] * 250)

        strategy._model = mock_model
        strategy._model_loaded = True

        df = make_ohlcv_df(rows=250)
        result = strategy.calculate(df)
        sell_signals = result[result["signal"] == -1]
        assert len(sell_signals) > 0

    def test_hold_signal(self, make_ohlcv_df):
        """Model predicting HOLD (class 1) → no signal."""
        strategy = MLStrategy(model_path="nonexistent.pkl", confidence_threshold=0.5)

        mock_model = MagicMock()
        mock_model.predict.return_value = np.array([[0.1, 0.8, 0.1]] * 250)

        strategy._model = mock_model
        strategy._model_loaded = True

        df = make_ohlcv_df(rows=250)
        result = strategy.calculate(df)
        signals = result[result["signal"] != 0]
        assert len(signals) == 0, "HOLD prediction should not produce signals"

    def test_get_params(self):
        strategy = MLStrategy(model_path="my_model.pkl", confidence_threshold=0.6)
        params = strategy.get_params()
        assert params["model_path"] == "my_model.pkl"
        assert params["confidence_threshold"] == 0.6

    def test_ml_confidence_column(self, make_ohlcv_df):
        """Calculate should add ml_confidence column."""
        strategy = MLStrategy(model_path="nonexistent.pkl")
        df = make_ohlcv_df(rows=250)
        result = strategy.calculate(df)
        assert "ml_confidence" in result.columns
