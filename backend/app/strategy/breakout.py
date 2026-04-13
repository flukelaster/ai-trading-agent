"""
Breakout Strategy — BUY when price breaks above N-period high channel,
SELL when price breaks below N-period low channel, filtered by ATR and volume.
"""

import pandas as pd

from app.strategy.base import BaseStrategy
from app.strategy.indicators import atr


class BreakoutStrategy(BaseStrategy):
    def __init__(
        self,
        lookback: int = 20,
        atr_period: int = 14,
        atr_threshold: float = 0.5,
        volume_filter: bool = True,
    ):
        self.lookback = lookback
        self.atr_period = atr_period
        self.atr_threshold = atr_threshold
        self.volume_filter = volume_filter

    @property
    def name(self) -> str:
        return "breakout"

    @property
    def min_bars_required(self) -> int:
        return self.lookback + self.atr_period + 5

    @property
    def worst_case(self) -> str:
        return "False breakouts in ranging markets — price spikes then immediately reverses"

    def get_params(self) -> dict:
        return {
            "lookback": self.lookback,
            "atr_period": self.atr_period,
            "atr_threshold": self.atr_threshold,
            "volume_filter": self.volume_filter,
        }

    def calculate(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()

        # Channel: N-period high/low (excluding current bar)
        df.loc[:, "high_channel"] = df["high"].shift(1).rolling(self.lookback).max()
        df.loc[:, "low_channel"] = df["low"].shift(1).rolling(self.lookback).min()
        df.loc[:, "atr"] = atr(df["high"], df["low"], df["close"], self.atr_period)

        # Volume filter: tick_volume above rolling average
        has_volume = "tick_volume" in df.columns
        if has_volume and self.volume_filter:
            df.loc[:, "vol_avg"] = df["tick_volume"].rolling(self.lookback).mean()
            vol_ok = df["tick_volume"] > df["vol_avg"]
        else:
            vol_ok = True

        df.loc[:, "signal"] = 0

        breakout_up = (df["close"] > df["high_channel"] + df["atr"] * self.atr_threshold) & vol_ok
        breakout_down = (df["close"] < df["low_channel"] - df["atr"] * self.atr_threshold) & vol_ok

        df.loc[breakout_up, "signal"] = 1
        df.loc[breakout_down, "signal"] = -1

        return df
