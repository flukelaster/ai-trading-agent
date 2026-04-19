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
                        Weights can be float (static) or callable(regime, performance) -> float (dynamic).
            symbol: Trading symbol.
        """
        self._strategies: list[tuple[BaseStrategy, float | callable]] = strategies
        self._symbol = symbol
        self._current_regime: str = "normal"
        self._strategy_performance: dict[str, float] = {}  # name -> recent win_rate

        # Normalize if static weights
        if all(isinstance(w, (int, float)) for _, w in strategies):
            total_weight = sum(w for _, w in strategies)
            if abs(total_weight - 1.0) > 0.01:
                logger.warning(f"Ensemble weights sum to {total_weight:.2f}, normalizing to 1.0")
                self._strategies = [(s, w / total_weight) for s, w in strategies]

    def set_regime(self, regime) -> None:
        """Update current regime for dynamic weight calculation."""
        self._current_regime = str(regime)

    def update_performance(self, strategy_name: str, win_rate: float) -> None:
        """Update rolling performance for a sub-strategy."""
        self._strategy_performance[strategy_name] = win_rate

    def _resolve_weight(self, weight, strategy_name: str) -> float:
        """Resolve weight — static float or dynamic callable."""
        if callable(weight):
            try:
                return weight(self._current_regime, self._strategy_performance.get(strategy_name, 0.5))
            except Exception:
                return 0.5
        return float(weight)

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
        for strategy, raw_weight in self._strategies:
            try:
                result = strategy.calculate(df.copy())
                resolved_w = self._resolve_weight(raw_weight, strategy.name)
                sub_signals.append((result["signal"], resolved_w, strategy.name))
            except Exception as e:
                logger.warning(f"Ensemble sub-strategy {strategy.name} failed: {e}")
                sub_signals.append((pd.Series(0, index=df.index), 0.0, strategy.name))

        # Normalize resolved weights
        total_w = sum(w for _, w, _ in sub_signals)
        if total_w > 0:
            sub_signals = [(s, w / total_w, n) for s, w, n in sub_signals]

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
            "strategies": [{"name": s.name, "weight": w, "params": s.get_params()} for s, w in self._strategies],
        }
