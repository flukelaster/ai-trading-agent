"""
RSI Filter Strategy — EMA crossover with RSI gate.
BUY: EMA cross up AND RSI < overbought
SELL: EMA cross down AND RSI > oversold
"""

import pandas as pd

from app.strategy.base import BaseStrategy
from app.strategy.indicators import ema, rsi, atr


class RSIFilterStrategy(BaseStrategy):
    def __init__(
        self,
        ema_fast: int = 20,
        ema_slow: int = 50,
        rsi_period: int = 14,
        rsi_overbought: int = 70,
        rsi_oversold: int = 30,
    ):
        self.ema_fast = ema_fast
        self.ema_slow = ema_slow
        self.rsi_period = rsi_period
        self.rsi_overbought = rsi_overbought
        self.rsi_oversold = rsi_oversold

    @property
    def name(self) -> str:
        return "rsi_filter"

    @property
    def min_bars_required(self) -> int:
        return max(self.ema_slow, self.rsi_period) + 5

    @property
    def worst_case(self) -> str:
        return "Extended overbought/oversold in strong trends — RSI stays extreme while price continues"

    def get_params(self) -> dict:
        return {
            "ema_fast": self.ema_fast,
            "ema_slow": self.ema_slow,
            "rsi_period": self.rsi_period,
            "rsi_overbought": self.rsi_overbought,
            "rsi_oversold": self.rsi_oversold,
        }

    def calculate(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()

        df["ema_fast"] = ema(df["close"], self.ema_fast)
        df["ema_slow"] = ema(df["close"], self.ema_slow)
        df["rsi"] = rsi(df["close"], self.rsi_period)
        df["atr"] = atr(df["high"], df["low"], df["close"], 14)

        df["signal"] = 0

        # RSI divergence detection (5-bar lookback)
        # Bearish divergence: price higher but RSI lower → weakening uptrend
        # Bullish divergence: price lower but RSI higher → weakening downtrend
        df["bearish_div"] = (df["close"] > df["close"].shift(5)) & (df["rsi"] < df["rsi"].shift(5))
        df["bullish_div"] = (df["close"] < df["close"].shift(5)) & (df["rsi"] > df["rsi"].shift(5))

        cross_up = (df["ema_fast"] > df["ema_slow"]) & (df["ema_fast"].shift(1) <= df["ema_slow"].shift(1))
        cross_down = (df["ema_fast"] < df["ema_slow"]) & (df["ema_fast"].shift(1) >= df["ema_slow"].shift(1))

        # Filter: skip BUY if bearish divergence, skip SELL if bullish divergence
        df.loc[cross_up & (df["rsi"] < self.rsi_overbought) & ~df["bearish_div"], "signal"] = 1
        df.loc[cross_down & (df["rsi"] > self.rsi_oversold) & ~df["bullish_div"], "signal"] = -1

        return df
