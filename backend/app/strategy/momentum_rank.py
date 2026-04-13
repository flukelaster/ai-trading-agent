"""
Cross-Asset Momentum Rank Strategy — go long the strongest, short the weakest.

Ranks all symbols by N-bar return. Strongest gets BUY, weakest gets SELL.
Falls back to absolute momentum on single-symbol when cross-data unavailable.

Worst case: momentum reversal — the strongest trending asset reverses sharply.
"""

import pandas as pd

from app.strategy.base import BaseStrategy
from app.strategy.indicators import atr, adx as calc_adx

ALL_SYMBOLS = ["GOLD", "OILCash", "BTCUSD", "USDJPY"]


class MomentumRankStrategy(BaseStrategy):
    def __init__(
        self,
        lookback: int = 20,
        atr_period: int = 14,
        symbol: str = "GOLD",
    ):
        self._lookback = lookback
        self._atr_period = atr_period
        self._symbol = symbol
        self._cross_returns: dict[str, float] = {}
        self._rank: int | None = None

    @property
    def name(self) -> str:
        return "momentum_rank"

    @property
    def min_bars_required(self) -> int:
        return self._lookback + self._atr_period + 10

    @property
    def worst_case(self) -> str:
        return "Momentum reversal — the strongest trending asset reverses sharply while the weakest mean-reverts upward"

    def get_params(self) -> dict:
        return {
            "lookback": self._lookback,
            "symbol": self._symbol,
            "rank": self._rank,
            "cross_returns": {k: round(v, 6) for k, v in self._cross_returns.items()},
        }

    async def _prepare_cross_data(self, market_data) -> None:
        """Fetch N-bar returns for all symbols and rank them."""
        import asyncio
        self._cross_returns = {}
        try:
            dfs = await asyncio.gather(*[
                market_data.get_ohlcv(sym, "M15", self._lookback + 10)
                for sym in ALL_SYMBOLS
            ])
            for sym, df in zip(ALL_SYMBOLS, dfs):
                if df is not None and not df.empty and len(df) >= self._lookback + 1:
                    close_now = df["close"].iloc[-1]
                    close_prev = df["close"].iloc[-self._lookback]
                    if close_prev > 0:
                        self._cross_returns[sym] = (close_now - close_prev) / close_prev
        except Exception:
            pass

        if self._symbol in self._cross_returns and len(self._cross_returns) >= 2:
            sorted_syms = sorted(self._cross_returns.keys(), key=lambda s: self._cross_returns[s], reverse=True)
            self._rank = sorted_syms.index(self._symbol)

    def calculate(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        df["signal"] = 0
        df["atr"] = atr(df["high"], df["low"], df["close"], self._atr_period)

        # ADX filter — only trade in trending markets
        adx_result = calc_adx(df["high"], df["low"], df["close"], 14)
        last_adx = adx_result["adx"].iloc[-1] if "adx" in adx_result else 20

        if last_adx < 20:
            self._last_reason = f"Momentum Rank HOLD — ADX {last_adx:.1f} < 20 (no trend)"
            return df

        n_symbols = len(self._cross_returns)

        if self._rank is not None and n_symbols >= 2:
            # Cross-asset ranking: apply signal to last bar only
            last_idx = len(df) - 1
            if self._rank == 0:  # strongest
                df.iloc[last_idx, df.columns.get_loc("signal")] = 1
                self._last_reason = f"Momentum Rank BUY — {self._symbol} ranked #1/{n_symbols} (return {self._cross_returns.get(self._symbol, 0):.2%})"
            elif self._rank == n_symbols - 1:  # weakest
                df.iloc[last_idx, df.columns.get_loc("signal")] = -1
                self._last_reason = f"Momentum Rank SELL — {self._symbol} ranked #{n_symbols}/{n_symbols} (return {self._cross_returns.get(self._symbol, 0):.2%})"
            else:
                self._last_reason = f"Momentum Rank HOLD — {self._symbol} ranked #{self._rank + 1}/{n_symbols} (middle)"
        else:
            # Fallback: absolute momentum (single-symbol)
            df["mom_return"] = df["close"].pct_change(self._lookback)
            atr_pct = df["atr"].iloc[-1] / df["close"].iloc[-1] if df["close"].iloc[-1] > 0 else 0
            threshold = max(atr_pct * 2, 0.005)

            for i in range(self._lookback, len(df)):
                ret = df.iloc[i]["mom_return"]
                if pd.notna(ret):
                    if ret > threshold:
                        df.iloc[i, df.columns.get_loc("signal")] = 1
                    elif ret < -threshold:
                        df.iloc[i, df.columns.get_loc("signal")] = -1

            signals = df[df["signal"] != 0]
            if not signals.empty:
                last = signals.iloc[-1]
                direction = "BUY" if last["signal"] == 1 else "SELL"
                self._last_reason = f"Abs Momentum {direction} — {self._lookback}-bar return={last.get('mom_return', 0):.2%}, threshold={threshold:.2%}"

        return df
