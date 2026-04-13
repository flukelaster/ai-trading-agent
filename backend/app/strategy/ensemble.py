"""
Ensemble Strategy — weighted voting from multiple sub-strategies.
Aggregates signals from multiple strategies to produce a consensus signal.
"""

import pandas as pd
from loguru import logger

from app.constants import ENSEMBLE_BUY_THRESHOLD, ENSEMBLE_SELL_THRESHOLD
from app.strategy.base import BaseStrategy
from app.strategy.indicators import atr


class EnsembleStrategy(BaseStrategy):
    def __init__(self, strategies: list[tuple[BaseStrategy, float]], symbol: str = "GOLD"):
        """
        Args:
            strategies: List of (strategy_instance, weight) tuples.
                        Weights should sum to ~1.0.
            symbol: Trading symbol.
        """
        self._strategies = strategies
        self._symbol = symbol
        total_weight = sum(w for _, w in strategies)
        if abs(total_weight - 1.0) > 0.01:
            logger.warning(f"Ensemble weights sum to {total_weight:.2f}, normalizing to 1.0")
            self._strategies = [(s, w / total_weight) for s, w in strategies]

    @property
    def name(self) -> str:
        names = "+".join(s.name for s, _ in self._strategies)
        return f"ensemble({names})"

    @property
    def min_bars_required(self) -> int:
        return max(s.min_bars_required for s, _ in self._strategies)

    @property
    def worst_case(self) -> str:
        return "All sub-strategies agree on wrong signal — correlated errors amplify losses"

    def calculate(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        df["signal"] = 0
        df["ensemble_confidence"] = 0.0
        df["atr"] = atr(df["high"], df["low"], df["close"], 14)

        # Collect signals from each sub-strategy
        sub_signals = []
        for strategy, weight in self._strategies:
            try:
                result = strategy.calculate(df.copy())
                sub_signals.append((result["signal"], weight, strategy.name))
            except Exception as e:
                logger.warning(f"Ensemble sub-strategy {strategy.name} failed: {e}")
                sub_signals.append((pd.Series(0, index=df.index), weight, strategy.name))

        # Weighted vote per bar
        for i in range(len(df)):
            weighted_sum = 0.0
            for signals, weight, _ in sub_signals:
                weighted_sum += signals.iloc[i] * weight

            if weighted_sum >= ENSEMBLE_BUY_THRESHOLD:
                df.iloc[i, df.columns.get_loc("signal")] = 1
            elif weighted_sum <= ENSEMBLE_SELL_THRESHOLD:
                df.iloc[i, df.columns.get_loc("signal")] = -1

            df.iloc[i, df.columns.get_loc("ensemble_confidence")] = abs(weighted_sum)

        return df

    def get_params(self) -> dict:
        return {
            "strategies": [
                {"name": s.name, "weight": w, "params": s.get_params()}
                for s, w in self._strategies
            ],
        }
