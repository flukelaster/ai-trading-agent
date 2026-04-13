"""
Grid Trading Strategy — buy below reference, sell above reference.

Places signals at regular price intervals around a moving average reference.
Stateless: grid levels recomputed each call from SMA.

Worst case: strong one-directional trend without mean reversion.
"""

import pandas as pd

from app.strategy.base import BaseStrategy
from app.strategy.indicators import atr


class GridStrategy(BaseStrategy):
    def __init__(
        self,
        grid_spacing_pips: float = 5.0,
        grid_levels: int = 5,
        sma_period: int = 20,
    ):
        self.grid_spacing_pips = grid_spacing_pips
        self.grid_levels = grid_levels
        self.sma_period = sma_period

    @property
    def name(self) -> str:
        return "grid"

    @property
    def min_bars_required(self) -> int:
        return self.sma_period + 5

    @property
    def worst_case(self) -> str:
        return "Strong one-directional trend without mean reversion — accumulates positions on wrong side with no grid profit to offset"

    def get_params(self) -> dict:
        return {
            "grid_spacing_pips": self.grid_spacing_pips,
            "grid_levels": self.grid_levels,
            "sma_period": self.sma_period,
        }

    def calculate(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        df["signal"] = 0
        df["atr"] = atr(df["high"], df["low"], df["close"], 14)
        df["sma_ref"] = df["close"].rolling(self.sma_period).mean()

        for i in range(self.sma_period, len(df)):
            ref = df.iloc[i]["sma_ref"]
            if pd.isna(ref):
                continue
            close = df.iloc[i]["close"]
            prev_close = df.iloc[i - 1]["close"]

            # Buy zones: price crosses below grid level
            for level in range(1, self.grid_levels + 1):
                grid_price = ref - (level * self.grid_spacing_pips)
                if prev_close >= grid_price > close:
                    df.iloc[i, df.columns.get_loc("signal")] = 1
                    break

            # Sell zones: price crosses above grid level
            if df.iloc[i]["signal"] == 0:
                for level in range(1, self.grid_levels + 1):
                    grid_price = ref + (level * self.grid_spacing_pips)
                    if prev_close <= grid_price < close:
                        df.iloc[i, df.columns.get_loc("signal")] = -1
                        break

        # Set last_reason
        signals = df[df["signal"] != 0]
        if not signals.empty:
            last = signals.iloc[-1]
            direction = "BUY (below grid)" if last["signal"] == 1 else "SELL (above grid)"
            self._last_reason = f"Grid {direction} — price={last['close']:.2f}, ref={last['sma_ref']:.2f}, spacing={self.grid_spacing_pips}"

        return df
