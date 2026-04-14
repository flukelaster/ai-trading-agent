"""MCP tools for quantitative analysis — VaR, GARCH volatility, regime, quant signals."""

import numpy as np


async def get_var_analysis(symbol: str, timeframe: str = "M15", count: int = 200, confidence: float = 0.95) -> dict:
    """Calculate Value-at-Risk for a symbol.

    Args:
        symbol: Trading symbol
        timeframe: Candle timeframe
        count: Number of candles for calculation
        confidence: VaR confidence level (default 0.95)

    Returns:
        Dict with VaR metrics (historical, parametric, expected shortfall).
    """
    from mcp_server.tools.market_data import get_ohlcv
    data = await get_ohlcv(symbol, timeframe, count)
    if "error" in data:
        return data

    prices = np.array([c["close"] for c in data["candles"]])
    if len(prices) < 30:
        return {"error": f"Insufficient data: {len(prices)} candles, need 30+"}

    returns = np.diff(np.log(prices))

    # Historical VaR
    hist_var = float(np.percentile(returns, (1 - confidence) * 100))

    # Parametric VaR (assumes normal distribution)
    from scipy.stats import norm
    mu = float(np.mean(returns))
    sigma = float(np.std(returns))
    param_var = float(mu + sigma * norm.ppf(1 - confidence))

    # Expected Shortfall (CVaR)
    tail = returns[returns <= hist_var]
    es = float(np.mean(tail)) if len(tail) > 0 else hist_var

    return {
        "symbol": symbol,
        "confidence": confidence,
        "historical_var": round(hist_var * 100, 4),
        "parametric_var": round(param_var * 100, 4),
        "expected_shortfall": round(es * 100, 4),
        "interpretation": f"At {confidence*100:.0f}% confidence, daily loss should not exceed {abs(hist_var)*100:.2f}%",
    }


async def get_volatility_forecast(symbol: str, timeframe: str = "M15", count: int = 200) -> dict:
    """Get GARCH volatility forecast vs realized volatility.

    Args:
        symbol: Trading symbol
        timeframe: Candle timeframe
        count: Number of candles

    Returns:
        Dict with current, forecast, and long-run volatility.
    """
    from mcp_server.tools.market_data import get_ohlcv
    data = await get_ohlcv(symbol, timeframe, count)
    if "error" in data:
        return data

    prices = np.array([c["close"] for c in data["candles"]])
    if len(prices) < 100:
        return {"error": f"Insufficient data: {len(prices)} candles, need 100+"}

    try:
        from app.risk.garch import fit_garch
        result = fit_garch(prices)
        d = result.to_dict()
        return {
            "symbol": symbol,
            "current_volatility": d["current_vol"],
            "forecast_1_period": d["forecast_1"],
            "forecast_5_period": d["forecast_5"],
            "long_run_volatility": d["long_run_vol"],
            "regime": d.get("regime", "normal"),
        }
    except Exception as e:
        # Fallback: simple realized volatility
        returns = np.diff(np.log(prices))
        vol = float(np.std(returns))
        return {
            "symbol": symbol,
            "current_volatility": round(vol * 100, 4),
            "note": f"GARCH unavailable ({e}), showing realized volatility",
        }


async def get_quant_signals(symbol: str, timeframe: str = "M15", count: int = 200) -> dict:
    """Get quantitative trading signals (momentum, mean-reversion, volatility breakout).

    Args:
        symbol: Trading symbol
        timeframe: Candle timeframe
        count: Number of candles

    Returns:
        Dict with signal values and interpretations.
    """
    from mcp_server.tools.market_data import get_ohlcv
    data = await get_ohlcv(symbol, timeframe, count)
    if "error" in data:
        return data

    import pandas as pd
    df = pd.DataFrame(data["candles"])
    for col in ("open", "high", "low", "close"):
        df[col] = df[col].astype(float)
    df["volume"] = df.get("volume", pd.Series([0] * len(df))).astype(float)

    if len(df) < 50:
        return {"error": f"Insufficient data: {len(df)} candles, need 50+"}

    close = df["close"]
    high = df["high"]
    low = df["low"]

    # Momentum (ROC)
    roc_20 = float((close.iloc[-1] / close.iloc[-20] - 1) * 100) if len(close) > 20 else 0

    # Z-score (mean reversion)
    rolling_mean = close.rolling(50).mean()
    rolling_std = close.rolling(50).std()
    z_score = float((close.iloc[-1] - rolling_mean.iloc[-1]) / rolling_std.iloc[-1]) if rolling_std.iloc[-1] > 0 else 0

    # Volatility breakout (ATR ratio)
    from app.strategy.indicators import atr
    atr_values = atr(high, low, close, 14)
    atr_avg = float(atr_values.rolling(50).mean().iloc[-1])
    atr_current = float(atr_values.iloc[-1])
    atr_ratio = atr_current / atr_avg if atr_avg > 0 else 1.0

    signals = {
        "symbol": symbol,
        "momentum_roc_20": round(roc_20, 4),
        "momentum_signal": "bullish" if roc_20 > 1 else "bearish" if roc_20 < -1 else "neutral",
        "mean_reversion_zscore": round(z_score, 4),
        "mean_reversion_signal": "oversold (buy)" if z_score < -2 else "overbought (sell)" if z_score > 2 else "neutral",
        "volatility_atr_ratio": round(atr_ratio, 4),
        "volatility_signal": "high (breakout)" if atr_ratio > 1.5 else "low (ranging)" if atr_ratio < 0.7 else "normal",
    }

    return signals
