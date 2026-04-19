"""MCP tools for technical indicators — wraps backend/app/strategy/indicators.py."""

import pandas as pd

from app.strategy.indicators import adx, atr, bollinger_bands, ema, rsi, stochastic
from mcp_server.tools.market_data import get_ohlcv


def _candles_to_df(candles: list[dict]) -> pd.DataFrame:
    """Convert candle list from MT5 to pandas DataFrame."""
    df = pd.DataFrame(candles)
    for col in ("open", "high", "low", "close"):
        if col in df.columns:
            df[col] = df[col].astype(float)
    return df


async def calculate_ema(symbol: str, period: int = 20, timeframe: str = "M15", count: int = 100) -> dict:
    """Calculate Exponential Moving Average.

    Args:
        symbol: Trading symbol
        period: EMA period (default 20)
        timeframe: Candle timeframe
        count: Number of candles

    Returns:
        Dict with latest EMA value and recent values.
    """
    data = await get_ohlcv(symbol, timeframe, count)
    if "error" in data:
        return data
    df = _candles_to_df(data["candles"])
    if len(df) < period:
        return {"error": f"Insufficient data: {len(df)} candles, need {period}"}
    values = ema(df["close"], period)
    return {
        "symbol": symbol,
        "period": period,
        "latest": round(float(values.iloc[-1]), 5),
        "previous": round(float(values.iloc[-2]), 5) if len(values) > 1 else None,
    }


async def calculate_rsi(symbol: str, period: int = 14, timeframe: str = "M15", count: int = 100) -> dict:
    """Calculate Relative Strength Index.

    Args:
        symbol: Trading symbol
        period: RSI period (default 14)
        timeframe: Candle timeframe
        count: Number of candles

    Returns:
        Dict with latest RSI value (0-100).
    """
    data = await get_ohlcv(symbol, timeframe, count)
    if "error" in data:
        return data
    df = _candles_to_df(data["candles"])
    if len(df) < period + 1:
        return {"error": f"Insufficient data: {len(df)} candles, need {period + 1}"}
    values = rsi(df["close"], period)
    latest = float(values.iloc[-1])
    return {
        "symbol": symbol,
        "period": period,
        "latest": round(latest, 2),
        "condition": "overbought" if latest > 70 else "oversold" if latest < 30 else "neutral",
    }


async def calculate_atr(symbol: str, period: int = 14, timeframe: str = "M15", count: int = 100) -> dict:
    """Calculate Average True Range (volatility measure).

    Args:
        symbol: Trading symbol
        period: ATR period (default 14)
        timeframe: Candle timeframe
        count: Number of candles

    Returns:
        Dict with latest ATR value.
    """
    data = await get_ohlcv(symbol, timeframe, count)
    if "error" in data:
        return data
    df = _candles_to_df(data["candles"])
    if len(df) < period + 1:
        return {"error": "Insufficient data"}
    values = atr(df["high"], df["low"], df["close"], period)
    return {
        "symbol": symbol,
        "period": period,
        "latest": round(float(values.iloc[-1]), 5),
    }


async def full_analysis(symbol: str, timeframe: str = "M15", count: int = 200) -> dict:
    """Run comprehensive technical analysis — EMA, RSI, ATR, ADX, Bollinger, Stochastic.

    This is the primary tool for the agent to get a full market picture.

    Args:
        symbol: Trading symbol
        timeframe: Candle timeframe
        count: Number of candles to analyze

    Returns:
        Dict with all indicator values and market conditions.
    """
    data = await get_ohlcv(symbol, timeframe, count)
    if "error" in data:
        return data

    df = _candles_to_df(data["candles"])
    if len(df) < 50:
        return {"error": f"Insufficient data: {len(df)} candles, need at least 50"}

    close = df["close"]
    high = df["high"]
    low = df["low"]
    last_close = float(close.iloc[-1])

    # EMAs
    ema_20 = ema(close, 20)
    ema_50 = ema(close, 50)

    # RSI
    rsi_values = rsi(close, 14)
    rsi_latest = float(rsi_values.iloc[-1])

    # ATR
    atr_values = atr(high, low, close, 14)
    atr_latest = float(atr_values.iloc[-1])

    # ADX
    adx_result = adx(high, low, close, 14)
    adx_latest = float(adx_result["adx"].iloc[-1])
    di_plus = float(adx_result["di_plus"].iloc[-1])
    di_minus = float(adx_result["di_minus"].iloc[-1])

    # Bollinger Bands
    bb = bollinger_bands(close, 20, 2.0)
    bb_upper = float(bb["upper"].iloc[-1])
    bb_lower = float(bb["lower"].iloc[-1])
    bb_pct_b = float(bb["pct_b"].iloc[-1])

    # Stochastic
    stoch = stochastic(high, low, close, 14, 3)
    stoch_k = float(stoch["k"].iloc[-1])
    stoch_d = float(stoch["d"].iloc[-1])

    # Trend assessment
    ema20_val = float(ema_20.iloc[-1])
    ema50_val = float(ema_50.iloc[-1])
    trend = "bullish" if ema20_val > ema50_val else "bearish" if ema20_val < ema50_val else "neutral"
    trend_strength = "strong" if adx_latest > 25 else "weak"

    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "last_close": round(last_close, 5),
        "ema_20": round(ema20_val, 5),
        "ema_50": round(ema50_val, 5),
        "rsi": round(rsi_latest, 2),
        "rsi_condition": "overbought" if rsi_latest > 70 else "oversold" if rsi_latest < 30 else "neutral",
        "atr": round(atr_latest, 5),
        "adx": round(adx_latest, 2),
        "di_plus": round(di_plus, 2),
        "di_minus": round(di_minus, 2),
        "bollinger_upper": round(bb_upper, 5),
        "bollinger_lower": round(bb_lower, 5),
        "bollinger_pct_b": round(bb_pct_b, 4),
        "stochastic_k": round(stoch_k, 2),
        "stochastic_d": round(stoch_d, 2),
        "trend": trend,
        "trend_strength": trend_strength,
        "price_vs_bb": "above_upper" if last_close > bb_upper else "below_lower" if last_close < bb_lower else "inside",
    }
