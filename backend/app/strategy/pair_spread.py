"""
Pair Spread Strategy — mean reversion on correlated pair spread (z-score).

GOLD and USDJPY have inverse correlation. Trades the z-score of their
normalized price spread. Entry at ±2σ, exit at ±0.5σ.

Falls back to single-symbol Bollinger z-score when pair data unavailable.

Worst case: correlation breakdown — pair decouples permanently.
"""

import pandas as pd
import numpy as np

from app.strategy.base import BaseStrategy
from app.strategy.indicators import atr

PAIR_MAP = {"GOLD": "USDJPY", "USDJPY": "GOLD"}


class PairSpreadStrategy(BaseStrategy):
    def __init__(
        self,
        z_entry: float = 2.0,
        z_exit: float = 0.5,
        lookback: int = 50,
        atr_period: int = 14,
        symbol: str = "GOLD",
        pair_symbol: str | None = None,
    ):
        self._z_entry = z_entry
        self._z_exit = z_exit
        self._lookback = lookback
        self._atr_period = atr_period
        self._symbol = symbol
        self._pair_symbol = pair_symbol or PAIR_MAP.get(symbol)
        self._pair_closes: pd.Series | None = None

    @property
    def name(self) -> str:
        return "pair_spread"

    @property
    def min_bars_required(self) -> int:
        return self._lookback + self._atr_period + 10

    @property
    def worst_case(self) -> str:
        return "Correlation breakdown — pair decouples permanently (e.g., USD crisis where both gold and yen move same direction)"

    def get_params(self) -> dict:
        return {
            "z_entry": self._z_entry,
            "z_exit": self._z_exit,
            "lookback": self._lookback,
            "symbol": self._symbol,
            "pair_symbol": self._pair_symbol,
        }

    async def _prepare_cross_data(self, market_data) -> None:
        """Fetch pair symbol OHLCV for spread calculation."""
        if not self._pair_symbol:
            return
        try:
            pair_df = await market_data.get_ohlcv(self._pair_symbol, "M15", 250)
            if pair_df is not None and not pair_df.empty and len(pair_df) >= self._lookback:
                self._pair_closes = pair_df["close"]
        except Exception:
            self._pair_closes = None

    def calculate(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        df["signal"] = 0
        df["atr"] = atr(df["high"], df["low"], df["close"], self._atr_period)

        if self._pair_closes is not None and len(self._pair_closes) >= self._lookback:
            df = self._calculate_pair_spread(df)
        else:
            df = self._calculate_single_zscore(df)

        return df

    def _calculate_pair_spread(self, df: pd.DataFrame) -> pd.DataFrame:
        """Pair spread z-score using normalized prices."""
        close_a = df["close"]

        # Align pair data to same length
        pair_len = min(len(close_a), len(self._pair_closes))
        close_a_aligned = close_a.iloc[-pair_len:].reset_index(drop=True)
        close_b_aligned = self._pair_closes.iloc[-pair_len:].reset_index(drop=True)

        # Normalize: price / rolling mean
        norm_a = close_a_aligned / close_a_aligned.rolling(self._lookback).mean()
        norm_b = close_b_aligned / close_b_aligned.rolling(self._lookback).mean()

        # Spread and z-score
        spread = norm_a - norm_b
        spread_mean = spread.rolling(self._lookback).mean()
        spread_std = spread.rolling(self._lookback).std()
        z_score = (spread - spread_mean) / spread_std.replace(0, np.nan)

        # Map z_score back to original df index
        offset = len(df) - pair_len
        df["z_score"] = np.nan
        for i in range(pair_len):
            if pd.notna(z_score.iloc[i]):
                df.iloc[offset + i, df.columns.get_loc("z_score")] = z_score.iloc[i]

        # Generate signals based on z-score
        is_inverted = self._symbol in ("USDJPY",)  # USDJPY is the "other side" of the pair

        for i in range(offset + self._lookback, len(df)):
            z = df.iloc[i]["z_score"]
            if pd.isna(z):
                continue

            if is_inverted:
                # USDJPY: buy when spread is high (USDJPY underperforming)
                if z > self._z_entry:
                    df.iloc[i, df.columns.get_loc("signal")] = 1
                elif z < -self._z_entry:
                    df.iloc[i, df.columns.get_loc("signal")] = -1
            else:
                # GOLD: buy when spread is low (GOLD underperforming)
                if z < -self._z_entry:
                    df.iloc[i, df.columns.get_loc("signal")] = 1
                elif z > self._z_entry:
                    df.iloc[i, df.columns.get_loc("signal")] = -1

        # Set reason
        last_z = df["z_score"].dropna()
        if not last_z.empty:
            z_val = last_z.iloc[-1]
            signals = df[df["signal"] != 0]
            if not signals.empty:
                direction = "BUY" if signals.iloc[-1]["signal"] == 1 else "SELL"
                self._last_reason = f"Pair Spread {direction} — {self._symbol}/{self._pair_symbol} z-score={z_val:.2f} (entry=±{self._z_entry})"
            else:
                self._last_reason = f"Pair Spread HOLD — z-score={z_val:.2f} (within ±{self._z_entry})"

        return df

    def _calculate_single_zscore(self, df: pd.DataFrame) -> pd.DataFrame:
        """Fallback: single-symbol Bollinger z-score mean reversion."""
        close = df["close"]
        rolling_mean = close.rolling(self._lookback).mean()
        rolling_std = close.rolling(self._lookback).std()
        z_score = (close - rolling_mean) / rolling_std.replace(0, np.nan)
        df["z_score"] = z_score

        for i in range(self._lookback, len(df)):
            z = df.iloc[i]["z_score"]
            if pd.isna(z):
                continue
            if z < -self._z_entry:
                df.iloc[i, df.columns.get_loc("signal")] = 1
            elif z > self._z_entry:
                df.iloc[i, df.columns.get_loc("signal")] = -1

        signals = df[df["signal"] != 0]
        if not signals.empty:
            last = signals.iloc[-1]
            direction = "BUY" if last["signal"] == 1 else "SELL"
            self._last_reason = f"Z-Score {direction} — {self._symbol} z={last['z_score']:.2f} (single-symbol fallback, entry=±{self._z_entry})"

        return df
