"""
Risk Parity Strategy — allocate position size inversely proportional to volatility.

Uses EMA crossover for signal direction, but the real value is the vol_weight:
less lot for volatile assets, more for calm ones. Engine reads vol_weight from get_params().

Worst case: low-volatility asset gets oversized position, then volatility spikes.
"""

import pandas as pd

from app.strategy.base import BaseStrategy
from app.strategy.indicators import atr, ema


ALL_SYMBOLS = ["GOLD", "OILCash", "BTCUSD", "USDJPY"]


class RiskParityStrategy(BaseStrategy):
    def __init__(
        self,
        ema_fast: int = 20,
        ema_slow: int = 50,
        atr_period: int = 14,
        vol_lookback: int = 50,
        symbol: str = "GOLD",
    ):
        self._ema_fast = ema_fast
        self._ema_slow = ema_slow
        self._atr_period = atr_period
        self._vol_lookback = vol_lookback
        self._symbol = symbol
        self._vol_weight: float = 0.25  # default equal weight
        self._all_vol_weights: dict[str, float] = {}

    @property
    def name(self) -> str:
        return "risk_parity"

    @property
    def min_bars_required(self) -> int:
        return max(self._vol_lookback, self._ema_slow) + 10

    @property
    def worst_case(self) -> str:
        return "Low-volatility asset gets oversized position, then volatility spikes — concentrated loss in the 'safe' asset"

    def get_params(self) -> dict:
        return {
            "ema_fast": self._ema_fast,
            "ema_slow": self._ema_slow,
            "vol_weight": round(self._vol_weight, 4),
            "all_weights": self._all_vol_weights,
        }

    async def _prepare_cross_data(self, market_data) -> None:
        """Fetch ATR of all symbols and compute inverse-volatility weights."""
        import asyncio
        atr_pcts = {}
        try:
            dfs = await asyncio.gather(*[
                market_data.get_ohlcv(sym, "M15", self._vol_lookback + 20)
                for sym in ALL_SYMBOLS
            ])
            for sym, df in zip(ALL_SYMBOLS, dfs):
                if df is not None and not df.empty and len(df) >= self._atr_period + 2:
                    atr_val = atr(df["high"], df["low"], df["close"], self._atr_period).iloc[-1]
                    price = df["close"].iloc[-1]
                    if price > 0:
                        atr_pcts[sym] = atr_val / price
        except Exception:
            pass

        if len(atr_pcts) >= 2:
            inv_vols = {sym: 1.0 / max(v, 0.0001) for sym, v in atr_pcts.items()}
            total = sum(inv_vols.values())
            self._all_vol_weights = {sym: round(v / total, 4) for sym, v in inv_vols.items()}
            self._vol_weight = self._all_vol_weights.get(self._symbol, 0.25)

    def calculate(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        df["signal"] = 0
        df["atr"] = atr(df["high"], df["low"], df["close"], self._atr_period)
        df["ema_fast"] = ema(df["close"], self._ema_fast)
        df["ema_slow"] = ema(df["close"], self._ema_slow)

        # EMA crossover signals
        for i in range(self._ema_slow + 1, len(df)):
            fast_prev = df.iloc[i - 1]["ema_fast"]
            fast_curr = df.iloc[i]["ema_fast"]
            slow_prev = df.iloc[i - 1]["ema_slow"]
            slow_curr = df.iloc[i]["ema_slow"]

            if fast_prev <= slow_prev and fast_curr > slow_curr:
                df.iloc[i, df.columns.get_loc("signal")] = 1
            elif fast_prev >= slow_prev and fast_curr < slow_curr:
                df.iloc[i, df.columns.get_loc("signal")] = -1

        signals = df[df["signal"] != 0]
        if not signals.empty:
            last = signals.iloc[-1]
            direction = "BUY" if last["signal"] == 1 else "SELL"
            self._last_reason = f"Risk Parity {direction} — vol_weight={self._vol_weight:.2%} (EMA{self._ema_fast}/{self._ema_slow} crossover)"

        return df
