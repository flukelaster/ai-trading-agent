"""
Mean-Reversion Strategy — Bollinger Band extremes + RSI confirmation.
Trades reversals when price reaches band extremes with RSI confirmation.
"""

import pandas as pd

from app.strategy.base import BaseStrategy
from app.strategy.indicators import atr, bollinger_bands, rsi


class MeanReversionStrategy(BaseStrategy):
    def __init__(
        self,
        bb_period: int = 20,
        bb_std: float = 2.0,
        rsi_period: int = 14,
        rsi_overbought: int = 70,
        rsi_oversold: int = 30,
        min_bandwidth: float = 0.005,
    ):
        self._bb_period = bb_period
        self._bb_std = bb_std
        self._rsi_period = rsi_period
        self._rsi_overbought = rsi_overbought
        self._rsi_oversold = rsi_oversold
        self._min_bandwidth = min_bandwidth

    @property
    def name(self) -> str:
        return "mean_reversion"

    @property
    def min_bars_required(self) -> int:
        return max(self._bb_period, self._rsi_period) + 10

    @property
    def worst_case(self) -> str:
        return "Strong trending market — price breaks through bands without reverting, losses compound"

    def calculate(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        df["signal"] = 0
        df["atr"] = atr(df["high"], df["low"], df["close"], 14)

        # Bollinger Bands
        bb = bollinger_bands(df["close"], self._bb_period, self._bb_std)
        df["bb_upper"] = bb["upper"]
        df["bb_lower"] = bb["lower"]
        df["bb_bandwidth"] = bb["bandwidth"]
        df["bb_pct_b"] = bb["pct_b"]

        # RSI
        df["rsi"] = rsi(df["close"], self._rsi_period)

        # Rolling min bandwidth for squeeze detection
        df["bb_bw_min5"] = df["bb_bandwidth"].rolling(5).min()

        # Generate signals
        for i in range(self._bb_period, len(df)):
            bw = df.iloc[i]["bb_bandwidth"]
            if pd.isna(bw) or bw < self._min_bandwidth:
                continue  # skip low bandwidth (squeeze / ranging)

            # Bollinger squeeze gate: skip if bandwidth is near 5-bar minimum
            # (squeeze about to break — mean reversion is dangerous here)
            bw_min5 = df.iloc[i].get("bb_bw_min5")
            if not pd.isna(bw_min5) and bw_min5 > 0 and bw < bw_min5 * 1.2:
                continue  # in or near squeeze, skip

            rsi_val = df.iloc[i]["rsi"]
            close = df.iloc[i]["close"]
            lower = df.iloc[i]["bb_lower"]
            upper = df.iloc[i]["bb_upper"]

            if close <= lower and rsi_val < self._rsi_oversold:
                df.iloc[i, df.columns.get_loc("signal")] = 1  # BUY reversal
            elif close >= upper and rsi_val > self._rsi_overbought:
                df.iloc[i, df.columns.get_loc("signal")] = -1  # SELL reversal

        return df

    def get_params(self) -> dict:
        return {
            "bb_period": self._bb_period,
            "bb_std": self._bb_std,
            "rsi_period": self._rsi_period,
            "rsi_overbought": self._rsi_overbought,
            "rsi_oversold": self._rsi_oversold,
            "min_bandwidth": self._min_bandwidth,
        }
