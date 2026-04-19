"""
Multi-Timeframe Filter — H4/D1 trend consensus with ADX qualifier.
Generalizes the original H1-only _get_h1_trend() to support multiple timeframes.
"""

import pandas as pd

from app.constants import MTF_ADX_TRENDING_THRESHOLD, MTF_EMA_ABOVE, MTF_EMA_BELOW


def get_trend(df: pd.DataFrame, timeframe: str = "", ema_period: int = 21) -> int:
    """
    Determine trend direction using EMA slope.
    Returns +1 (uptrend), -1 (downtrend), or 0 (neutral/insufficient data).
    """
    if df is None or df.empty or len(df) < ema_period + 1:
        return 0
    try:
        from app.strategy.indicators import ema as _ema

        closes = df["close"]
        ema_val = _ema(closes, ema_period).iloc[-1]
        current_price = closes.iloc[-1]
        if current_price > ema_val * MTF_EMA_ABOVE:
            return 1
        elif current_price < ema_val * MTF_EMA_BELOW:
            return -1
        return 0
    except Exception:
        return 0


def get_trend_strength(df: pd.DataFrame) -> float:
    """Get ADX value for trend strength assessment. Returns 0 if insufficient data."""
    if df is None or df.empty or len(df) < 20:
        return 0
    try:
        from app.strategy.indicators import adx

        result = adx(df["high"], df["low"], df["close"], 14)
        val = result["adx"].iloc[-1]
        return float(val) if pd.notna(val) else 0
    except Exception:
        return 0


def get_mtf_consensus(trends: dict[str, int], adx_values: dict[str, float] | None = None) -> int:
    """
    Compute multi-timeframe trend consensus.

    Logic:
    - If all timeframes agree → return that direction (strong filter)
    - If majority agree → return that direction (moderate filter)
    - If no agreement → return 0 (neutral, don't filter)
    - ADX qualifier: only count timeframes where ADX > threshold (trending)
    """
    if not trends:
        return 0

    effective_trends = {}
    for tf, trend in trends.items():
        if trend == 0:
            continue  # neutral doesn't count
        # ADX qualifier: skip if market is ranging on this timeframe
        if adx_values and tf in adx_values:
            if adx_values[tf] < MTF_ADX_TRENDING_THRESHOLD:
                continue  # ranging — don't trust trend direction
        effective_trends[tf] = trend

    if not effective_trends:
        return 0  # no trending timeframes → no filter

    values = list(effective_trends.values())
    # Unanimous or majority agreement
    up_count = sum(1 for v in values if v == 1)
    down_count = sum(1 for v in values if v == -1)

    if up_count > down_count and up_count >= len(values) / 2:
        return 1
    elif down_count > up_count and down_count >= len(values) / 2:
        return -1
    return 0
