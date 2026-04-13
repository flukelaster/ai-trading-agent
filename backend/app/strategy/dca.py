"""
DCA (Dollar-Cost Averaging) Strategy — buy at fixed intervals, no indicators.

The simplest possible strategy: buy every N bars regardless of price.
No sell signals — exit via TP, manual close, or drawdown limit.

Worst case: price drops continuously with no recovery.
"""

import pandas as pd

from app.strategy.base import BaseStrategy
from app.strategy.indicators import atr


class DCAStrategy(BaseStrategy):
    def __init__(self, interval_bars: int = 20):
        self.interval_bars = interval_bars

    @property
    def name(self) -> str:
        return "dca"

    @property
    def min_bars_required(self) -> int:
        return self.interval_bars + 1

    @property
    def worst_case(self) -> str:
        return "Price drops continuously with no recovery — accumulates large unrealized loss at progressively worse prices"

    def get_params(self) -> dict:
        return {"interval_bars": self.interval_bars}

    def calculate(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        df["signal"] = 0
        df["atr"] = atr(df["high"], df["low"], df["close"], 14)

        # BUY every N bars — no indicators, no conditions
        for i in range(self.interval_bars, len(df), self.interval_bars):
            df.iloc[i, df.columns.get_loc("signal")] = 1

        # Set last_reason
        buy_indices = df.index[df["signal"] == 1]
        if len(buy_indices) > 0:
            self._last_reason = f"DCA scheduled buy (every {self.interval_bars} bars)"

        return df
