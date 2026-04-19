"""
ML Feature Engineering — builds features and labels from OHLCV data for model training.
"""

import numpy as np
import pandas as pd

from app.strategy.indicators import atr, ema, rsi

# All feature column names — must match between training and inference
FEATURE_COLUMNS = [
    # EMAs
    "ema_9",
    "ema_21",
    "ema_50",
    "ema_200",
    "price_vs_ema9",
    "price_vs_ema21",
    "price_vs_ema50",
    "price_vs_ema200",
    # RSI
    "rsi_14",
    # ATR & volatility
    "atr_14",
    "atr_pct",
    "atr_percentile",
    "rolling_std_10",
    "rolling_std_20",
    # Bollinger Bands
    "bb_upper",
    "bb_lower",
    "bb_width",
    "bb_position",
    # MACD
    "macd",
    "macd_signal",
    "macd_histogram",
    # Stochastic
    "stoch_k",
    "stoch_d",
    # Price action
    "candle_body_ratio",
    "upper_shadow_ratio",
    "lower_shadow_ratio",
    "gap_pct",
    # Momentum
    "roc_5",
    "roc_10",
    "roc_20",
    # Time features (cyclical encoding)
    "hour_sin",
    "hour_cos",
    "dow_sin",
    "dow_cos",
    # Session flags
    "is_london",
    "is_ny",
    "is_overlap",
    # Volume
    "volume_sma_ratio",
    # ADX regime
    "adx_14",
    "adx_di_plus",
    "adx_di_minus",
    # Sentiment (populated if sentiment_df provided)
    "sent_score_mean",
    "sent_confidence_mean",
    "sent_bullish_ratio",
    "sent_bearish_ratio",
    "sent_count",
    "sent_momentum_3d",
]


def build_features(
    df: pd.DataFrame, macro_df: pd.DataFrame | None = None, sentiment_df: pd.DataFrame | None = None
) -> pd.DataFrame:
    """
    Build ML features from OHLCV DataFrame.
    Input df must have columns: open, high, low, close and optionally tick_volume.
    Index should be DatetimeIndex.
    """
    out = df.copy()
    c = out["close"]
    h = out["high"]
    low_s = out["low"]
    o = out["open"]
    v = out.get("tick_volume", pd.Series(0, index=out.index))

    # EMAs
    out["ema_9"] = ema(c, 9)
    out["ema_21"] = ema(c, 21)
    out["ema_50"] = ema(c, 50)
    out["ema_200"] = ema(c, 200)
    out["price_vs_ema9"] = (c - out["ema_9"]) / out["ema_9"] * 100
    out["price_vs_ema21"] = (c - out["ema_21"]) / out["ema_21"] * 100
    out["price_vs_ema50"] = (c - out["ema_50"]) / out["ema_50"] * 100
    out["price_vs_ema200"] = (c - out["ema_200"]) / out["ema_200"] * 100

    # RSI
    out["rsi_14"] = rsi(c, 14)

    # ATR & volatility
    out["atr_14"] = atr(h, low_s, c, 14)
    out["atr_pct"] = out["atr_14"] / c * 100
    out["atr_percentile"] = out["atr_14"].rolling(100).rank(pct=True)
    out["rolling_std_10"] = c.pct_change().rolling(10).std()
    out["rolling_std_20"] = c.pct_change().rolling(20).std()

    # Bollinger Bands (20-period, 2 std)
    sma_20 = c.rolling(20).mean()
    std_20 = c.rolling(20).std()
    out["bb_upper"] = sma_20 + 2 * std_20
    out["bb_lower"] = sma_20 - 2 * std_20
    out["bb_width"] = (out["bb_upper"] - out["bb_lower"]) / sma_20 * 100
    out["bb_position"] = (c - out["bb_lower"]) / (out["bb_upper"] - out["bb_lower"])

    # MACD
    ema_12 = ema(c, 12)
    ema_26 = ema(c, 26)
    out["macd"] = ema_12 - ema_26
    out["macd_signal"] = ema(out["macd"], 9)
    out["macd_histogram"] = out["macd"] - out["macd_signal"]

    # Stochastic %K/%D (14 period)
    low_14 = low_s.rolling(14).min()
    high_14 = h.rolling(14).max()
    out["stoch_k"] = (c - low_14) / (high_14 - low_14) * 100
    out["stoch_d"] = out["stoch_k"].rolling(3).mean()

    # Price action
    body = (c - o).abs()
    full_range = h - low_s
    out["candle_body_ratio"] = body / full_range.replace(0, np.nan)
    out["upper_shadow_ratio"] = (h - pd.concat([c, o], axis=1).max(axis=1)) / full_range.replace(0, np.nan)
    out["lower_shadow_ratio"] = (pd.concat([c, o], axis=1).min(axis=1) - low_s) / full_range.replace(0, np.nan)
    out["gap_pct"] = (o - c.shift(1)) / c.shift(1) * 100

    # Momentum (Rate of Change)
    out["roc_5"] = c.pct_change(5) * 100
    out["roc_10"] = c.pct_change(10) * 100
    out["roc_20"] = c.pct_change(20) * 100

    # Time features (cyclical encoding)
    if hasattr(out.index, "hour"):
        hour = out.index.hour
        dow = out.index.dayofweek
    else:
        hour = pd.Series(0, index=out.index)
        dow = pd.Series(0, index=out.index)

    out["hour_sin"] = np.sin(2 * np.pi * hour / 24)
    out["hour_cos"] = np.cos(2 * np.pi * hour / 24)
    out["dow_sin"] = np.sin(2 * np.pi * dow / 5)
    out["dow_cos"] = np.cos(2 * np.pi * dow / 5)

    # Session flags
    out["is_london"] = ((hour >= 8) & (hour < 16)).astype(int)
    out["is_ny"] = ((hour >= 13) & (hour < 21)).astype(int)
    out["is_overlap"] = ((hour >= 13) & (hour < 16)).astype(int)

    # Volume
    vol_sma = v.rolling(20).mean()
    out["volume_sma_ratio"] = v / vol_sma.replace(0, np.nan)

    # ADX (Average Directional Index) — regime detection
    from app.strategy.indicators import adx as _adx

    adx_result = _adx(h, low_s, c, 14)
    out["adx_14"] = adx_result["adx"]
    out["adx_di_plus"] = adx_result["di_plus"]
    out["adx_di_minus"] = adx_result["di_minus"]

    # Merge macro data if available
    if macro_df is not None and not macro_df.empty:
        out = _merge_macro_features(out, macro_df)

    # Merge sentiment data if available
    if sentiment_df is not None and not sentiment_df.empty:
        out = _merge_sentiment_features(out, sentiment_df)

    return out


def build_labels(
    df: pd.DataFrame,
    forward_bars: int = 10,
    tp_pips: float = 5.0,
    sl_pips: float = 5.0,
) -> pd.Series:
    """
    Triple Barrier Labeling:
    - Barrier 1 (UP):   highest high in next forward_bars >= entry + tp_pips → BUY (1)
    - Barrier 2 (DOWN): lowest low in next forward_bars <= entry - sl_pips   → SELL (-1)
    - Barrier 3 (TIME): neither hit within forward_bars                       → HOLD (0)

    When both barriers could be hit, whichever is hit FIRST wins.
    Last forward_bars rows are dropped (NaN) since they can't be labeled.
    tp_pips is the long TP; sl_pips is the long SL. For short signals the barriers swap.
    """
    labels = pd.Series(np.nan, index=df.index, dtype=float)
    closes = df["close"].values
    highs = df["high"].values
    lows = df["low"].values
    n = len(df)

    for i in range(n - forward_bars):
        entry = closes[i]
        tp_long = entry + tp_pips  # long TP
        entry - sl_pips  # long SL (= short TP)
        tp_short = entry - tp_pips  # short TP
        entry + sl_pips  # short SL (= long SL for short)

        long_hit = None
        short_hit = None

        for j in range(i + 1, min(i + forward_bars + 1, n)):
            if long_hit is None and highs[j] >= tp_long:
                long_hit = j
            if short_hit is None and lows[j] <= tp_short:
                short_hit = j

            # Once both hit or first one hit, no need to continue
            if long_hit is not None and short_hit is not None:
                break

        if long_hit is None and short_hit is None:
            labels.iloc[i] = 0  # timeout — no conviction
        elif long_hit is not None and short_hit is None:
            labels.iloc[i] = 1  # BUY
        elif short_hit is not None and long_hit is None:
            labels.iloc[i] = -1  # SELL
        else:
            # Both hit — whichever came first wins
            labels.iloc[i] = 1 if long_hit <= short_hit else -1

    return labels


def _merge_macro_features(df: pd.DataFrame, macro_df: pd.DataFrame) -> pd.DataFrame:
    """Merge macro data into OHLCV features with forward-fill."""
    # macro_df expected columns: date, series_id, value (pivoted to columns)
    if "date" in macro_df.columns:
        macro_df = macro_df.set_index("date")

    # Align to OHLCV dates
    macro_df.index = pd.to_datetime(macro_df.index)
    df_date = df.index.normalize()  # strip time for daily macro merge

    for col in macro_df.columns:
        if col in ("series_id",):
            continue
        # Map macro values to OHLCV bars by date
        mapped = df_date.map(macro_df[col].reindex(macro_df.index).to_dict())
        df[f"macro_{col}"] = pd.to_numeric(mapped, errors="coerce")
        df[f"macro_{col}"] = df[f"macro_{col}"].ffill()

    return df


def _merge_sentiment_features(df: pd.DataFrame, sentiment_df: pd.DataFrame) -> pd.DataFrame:
    """Merge daily sentiment aggregates into OHLCV features with forward-fill."""
    sentiment_df = sentiment_df.copy()
    sentiment_df.index = pd.to_datetime(sentiment_df.index)
    df_date = df.index.normalize()

    for col in sentiment_df.columns:
        mapped = df_date.map(sentiment_df[col].to_dict())
        df[col] = pd.to_numeric(mapped, errors="coerce")
        df[col] = df[col].ffill()

    return df
