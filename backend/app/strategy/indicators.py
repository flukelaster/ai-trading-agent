"""
Technical indicators — pure pandas/numpy, no external dependencies.
"""

import numpy as np
import pandas as pd


def ema(series: pd.Series, length: int) -> pd.Series:
    return series.ewm(span=length, adjust=False).mean()


def rsi(series: pd.Series, length: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = (-delta).where(delta < 0, 0.0)
    avg_gain = gain.ewm(span=length, adjust=False).mean()
    avg_loss = loss.ewm(span=length, adjust=False).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def atr(high: pd.Series, low: pd.Series, close: pd.Series, length: int = 14) -> pd.Series:
    prev_close = close.shift(1)
    tr = pd.concat(
        [
            high - low,
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr.ewm(span=length, adjust=False).mean()


def adx(high: pd.Series, low: pd.Series, close: pd.Series, length: int = 14) -> dict:
    """
    Average Directional Index (ADX) with +DI and -DI.
    Returns dict with keys: adx, di_plus, di_minus.
    ADX > 25 = trending market, < 20 = ranging/sideways.
    """
    prev_high = high.shift(1)
    prev_low = low.shift(1)
    prev_close = close.shift(1)

    # True Range
    tr = pd.concat(
        [
            high - low,
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)

    # Directional movement
    up_move = high - prev_high
    down_move = prev_low - low

    plus_dm = pd.Series(np.where((up_move > down_move) & (up_move > 0), up_move, 0.0), index=high.index)
    minus_dm = pd.Series(np.where((down_move > up_move) & (down_move > 0), down_move, 0.0), index=high.index)

    # Smoothed TR and DM (Wilder's smoothing = EMA with span=length)
    atr_smooth = tr.ewm(span=length, adjust=False).mean()
    plus_dm_smooth = plus_dm.ewm(span=length, adjust=False).mean()
    minus_dm_smooth = minus_dm.ewm(span=length, adjust=False).mean()

    di_plus = (plus_dm_smooth / atr_smooth.replace(0, np.nan)) * 100
    di_minus = (minus_dm_smooth / atr_smooth.replace(0, np.nan)) * 100

    dx = (abs(di_plus - di_minus) / (di_plus + di_minus).replace(0, np.nan)) * 100
    adx_line = dx.ewm(span=length, adjust=False).mean()

    return {"adx": adx_line, "di_plus": di_plus, "di_minus": di_minus}


def bollinger_bands(series: pd.Series, length: int = 20, std_dev: float = 2.0) -> dict:
    """Bollinger Bands: middle (SMA), upper, lower, bandwidth, %B."""
    middle = series.rolling(length).mean()
    std = series.rolling(length).std()
    upper = middle + std * std_dev
    lower = middle - std * std_dev
    bandwidth = (upper - lower) / middle  # normalized bandwidth
    pct_b = (series - lower) / (upper - lower)  # %B (0=lower, 1=upper)
    return {"middle": middle, "upper": upper, "lower": lower, "bandwidth": bandwidth, "pct_b": pct_b}


def stochastic(high: pd.Series, low: pd.Series, close: pd.Series, k_period: int = 14, d_period: int = 3) -> dict:
    """Stochastic oscillator: %K and %D."""
    lowest_low = low.rolling(k_period).min()
    highest_high = high.rolling(k_period).max()
    k = 100 * (close - lowest_low) / (highest_high - lowest_low)
    d = k.rolling(d_period).mean()
    return {"k": k, "d": d}
