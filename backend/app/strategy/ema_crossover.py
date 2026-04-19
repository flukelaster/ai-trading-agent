"""
EMA Crossover Strategy — BUY when fast EMA crosses above slow EMA, SELL on cross below.
"""

import pandas as pd

from app.strategy.base import BaseStrategy
from app.strategy.indicators import atr, ema


class EMACrossoverStrategy(BaseStrategy):
    def __init__(self, fast_period: int = 20, slow_period: int = 50):
        self.fast_period = fast_period
        self.slow_period = slow_period

    @property
    def name(self) -> str:
        return "ema_crossover"

    @property
    def min_bars_required(self) -> int:
        return self.slow_period + 5

    @property
    def worst_case(self) -> str:
        return "Choppy/ranging markets cause repeated false crossovers and whipsaw losses"

    def get_params(self) -> dict:
        return {"fast_period": self.fast_period, "slow_period": self.slow_period}

    def calculate(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()

        df["ema_fast"] = ema(df["close"], self.fast_period)
        df["ema_slow"] = ema(df["close"], self.slow_period)
        df["atr"] = atr(df["high"], df["low"], df["close"], 14)

        df["signal"] = 0

        cross_up = (df["ema_fast"] > df["ema_slow"]) & (df["ema_fast"].shift(1) <= df["ema_slow"].shift(1))
        cross_down = (df["ema_fast"] < df["ema_slow"]) & (df["ema_fast"].shift(1) >= df["ema_slow"].shift(1))

        df.loc[cross_up, "signal"] = 1
        df.loc[cross_down, "signal"] = -1

        return df
